"""End-to-end pipeline: face scan -> genuine reverse-image search -> pick a
real matching social media post -> anchor the match on a blockchain.

Usage:
    python -m faceid.run --image demo/input_face.jpg --chain local
    python -m faceid.run --image demo/input_face.jpg --chain amoy
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import pathlib
import sys

import cv2
from dotenv import load_dotenv

if sys.stdout.encoding is None or sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding is None or sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from . import console as console_mod
from . import face, record, search
from .chain import Chain

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "out"


def log(msg: str) -> None:
    console_mod.log(msg, prefix="run")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Path to the input face photo")
    parser.add_argument(
        "--chain", choices=["local", "amoy"], default="local",
        help="'local' = in-process EVM (no network needed); 'amoy' = real Polygon Amoy testnet",
    )
    parser.add_argument(
        "--max-candidates", type=int, default=8,
        help="Max number of social-media search results to re-verify by face embedding",
    )
    parser.add_argument(
        "--force-redeploy", action="store_true",
        help="Deploy a fresh FaceRegistry contract instead of reusing out/deployment.json",
    )
    args = parser.parse_args()

    load_dotenv()
    OUT_DIR.mkdir(exist_ok=True)

    image_path = pathlib.Path(args.image)
    if not image_path.exists():
        log(f"ERROR: input image not found: {image_path}")
        return 1

    # ---- Step 1: detect + encode the query face ----------------------
    console_mod.rule("Step 1/5 — Detect + encode face")
    log(f"Step 1/5: detecting + encoding face in {image_path}")
    query_face = face.detect_and_embed(str(image_path))
    if query_face is None:
        log("ERROR: no face detected in input image.")
        return 1
    log(
        f"  found {query_face.num_faces_detected} face(s); using highest-confidence "
        f"(score={query_face.detect_score:.3f}, bbox={query_face.bbox})"
    )
    crop_path = OUT_DIR / "01_face_crop.jpg"
    face.save_crop(query_face, crop_path)
    query_embedding_sha = record.sha256_bytes(query_face.embedding.tobytes())
    (OUT_DIR / "02_embedding.json").write_text(
        json.dumps(
            {
                "embedding": query_face.embedding.tolist(),
                "embedding_sha256": query_embedding_sha,
                "detect_score": query_face.detect_score,
            },
            indent=2,
        )
    )
    log(f"  saved crop -> {crop_path}, embedding sha256={query_embedding_sha[:16]}...")

    # ---- Step 2: publish the crop publicly ----------------------------
    console_mod.rule("Step 2/5 — Publish crop publicly")
    log("Step 2/5: uploading face crop to a public temp host (needed for Lens)")
    public_url = search.upload_public_image(crop_path)
    log(f"  public URL: {public_url}")

    # ---- Step 3: genuine Google Lens reverse-image search -------------
    console_mod.rule("Step 3/5 — Genuine reverse-image search")
    log("Step 3/5: querying SerpAPI Google Lens (genuine web search, not cached)")
    try:
        with console_mod.spinner("Querying SerpAPI Google Lens..."):
            lens_raw = search.google_lens_search(public_url)
    except search.SearchError as e:
        log(f"ERROR: {e}")
        return 1
    (OUT_DIR / "03_lens_raw.json").write_text(json.dumps(lens_raw, indent=2))
    candidates = search.extract_social_candidates(lens_raw)
    log(f"  raw response saved -> out/03_lens_raw.json ({len(lens_raw.get('visual_matches', []))} total visual matches)")
    log(f"  {len(candidates)} candidate(s) on recognized social platforms")
    if not candidates:
        log("ERROR: no social-media candidates found in search results. Stopping "
            "(no blockchain anchor is written for a non-match).")
        return 1

    # ---- Step 4: independently confirm the match by face embedding ----
    console_mod.rule("Step 4/5 — Independently re-verify candidates")
    log("Step 4/5: independently re-verifying candidates by face embedding (not trusting Lens alone)")
    import requests

    best = None
    best_image_bytes = None
    checked = []
    with console_mod.spinner("Re-downloading + re-embedding candidates..."):
        for cand in candidates[: args.max_candidates]:
            img_url = cand.get("thumbnail")
            if not img_url:
                log(f"  skip {cand['link']!r}: no thumbnail image URL from Lens (cannot use webpage link as an image)")
                checked.append({"link": cand["link"], "title": cand["title"], "cosine": None, "skipped_reason": "no_thumbnail"})
                continue
            try:
                resp = requests.get(img_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                cand_face = face.detect_and_embed(resp.content)
            except Exception as e:
                log(f"  skip {cand['link']!r}: {e}")
                continue
            if cand_face is None:
                log(f"  skip {cand['link']!r}: no face detected in candidate image")
                continue
            score = face.cosine(query_face.embedding, cand_face.embedding)
            checked.append({"link": cand["link"], "title": cand["title"], "cosine": score})
            log(f"  {cand['link']} -> cosine={score:.3f}")
            if score >= face.SFACE_MATCH_THRESHOLD and (best is None or score > best["cosine"]):
                best = {**cand, "cosine": score}
                best_image_bytes = resp.content

    match_report = {"checked": checked, "match": best}
    (OUT_DIR / "04_match.json").write_text(json.dumps(match_report, indent=2))

    if best is None:
        best_score = max((c["cosine"] for c in checked if c["cosine"] is not None), default=0.0)
        log(
            f"ERROR: no candidate passed the {face.SFACE_MATCH_THRESHOLD} cosine threshold "
            f"(best={best_score:.3f}). No blockchain anchor written -- this is an honest "
            f"'no match' result, not a failure to search."
        )
        return 1

    log(f"  VERIFIED MATCH: {best['link']} (cosine={best['cosine']:.3f})")

    # ---- Step 5: build the record + anchor on-chain --------------------
    console_mod.rule("Step 5/5 — Build record + anchor on-chain")
    log("Step 5/5: building match record and anchoring on-chain")
    match_image_sha = record.sha256_bytes(best_image_bytes)
    match_record = {
        "query_image_sha256": record.sha256_file(str(image_path)),
        "query_embedding_sha256": query_embedding_sha,
        "matched_post_url": best["link"],
        "matched_post_title": best["title"],
        "matched_post_source": best.get("source", ""),
        "matched_image_sha256": match_image_sha,
        "cosine_similarity": round(best["cosine"], 6),
        "match_threshold": face.SFACE_MATCH_THRESHOLD,
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "detector": "opencv-yunet-2023mar",
        "recognizer": "opencv-sface-2021dec",
        "search_engine": "serpapi-google-lens",
    }
    (OUT_DIR / "05_record.json").write_text(json.dumps(match_record, indent=2, sort_keys=True))
    rhash = record.record_hash(match_record)
    log(f"  record hash (keccak256): 0x{rhash.hex()}")

    chain = Chain(args.chain)
    contract_addr = chain.deploy_or_load(force_new=args.force_redeploy)
    log(f"  contract at {contract_addr} on {args.chain}")

    uri = best["link"]
    ipfs_cid = None
    try:
        from . import ipfs
        if ipfs.is_configured():
            log("  pinning full match record to IPFS (optional, PINATA_JWT set)...")
            ipfs_cid = ipfs.pin_record(match_record)
            if ipfs_cid:
                uri = f"{best['link']} | ipfs://{ipfs_cid}"
                log(f"  pinned -> ipfs://{ipfs_cid}  ({ipfs.gateway_url(ipfs_cid)})")
    except Exception as e:
        log(f"  WARNING: IPFS pin skipped (non-fatal): {e}")

    receipt = chain.anchor(rhash, uri)
    if ipfs_cid:
        receipt["ipfs_cid"] = ipfs_cid
        receipt["ipfs_gateway_url"] = ipfs.gateway_url(ipfs_cid)
    (OUT_DIR / "06_receipt.json").write_text(json.dumps(receipt, indent=2))
    log(f"  ANCHORED. tx={receipt['tx_hash']} block={receipt['block_number']}")
    if receipt.get("explorer_tx_url"):
        log(f"  explorer: {receipt['explorer_tx_url']}")

    if args.chain == "amoy":
        log("Done. Re-verify anytime (even from a different machine) with: "
            f"python -m faceid.verify --chain amoy --record out/05_record.json")
    else:
        # eth-tester's local EVM is in-process only and does not persist
        # across separate script invocations, so demonstrate the
        # verify + tamper-evidence story here, in the same process,
        # against the contract we just deployed. For a persistent,
        # cross-process/public verification story use --chain amoy.
        log("Chain is 'local' (in-process, non-persistent) -- demonstrating "
            "re-verification in this same run:")
        good = chain.verify(rhash)
        log(f"  verify(original hash)  -> exists={good['exists']} uri={good['uri']}")
        tampered_record = dict(match_record)
        tampered_record["cosine_similarity"] = round(match_record["cosine_similarity"] + 0.05, 6)
        tampered_hash = record.record_hash(tampered_record)
        bad = chain.verify(tampered_hash)
        log(f"  verify(tampered hash)  -> exists={bad['exists']} (tamper correctly rejected)"
            if not bad["exists"] else "  WARNING: tampered hash unexpectedly matched!")
        log("For a persistent, publicly re-checkable record, rerun with --chain amoy.")

    try:
        from . import certificate
        cert_path = OUT_DIR / "07_certificate.png"
        certificate.generate_certificate(
            query_crop_path=crop_path,
            matched_image_bytes=best_image_bytes,
            match_record=match_record,
            record_hash_hex="0x" + rhash.hex(),
            receipt=receipt,
            chain_mode=args.chain,
            dest_path=cert_path,
        )
        log(f"Bonus: verification certificate -> {cert_path}")
    except Exception as e:
        log(f"WARNING: certificate generation failed (non-fatal): {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
