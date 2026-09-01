"""Run the full face -> search -> match -> anchor pipeline over a batch of
demo images and record structured results for a test report.

Uses --chain local (in-process EVM) for every run so this can execute as
many times as needed with no gas cost and no shared testnet state; the
persistent, publicly re-checkable Amoy anchor is demonstrated separately
(see out/06_receipt.json from a --chain amoy run).

Writes:
  out/batch/<NN>_<slug>/            -- per-image artifacts (same shape as out/*.json from run.py)
  out/batch_test_results.json       -- machine-readable summary of every test
"""
from __future__ import annotations

import datetime as dt
import io
import json
import pathlib
import sys
import time
import traceback

import requests
from dotenv import load_dotenv

if sys.stdout.encoding is None or sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from faceid import face, record, search  # noqa: E402
from faceid.chain import Chain  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
BATCH_DIR = ROOT / "demo" / "batch"
OUT_DIR = ROOT / "out" / "batch"
RESULTS_PATH = ROOT / "out" / "batch_test_results.json"

MAX_CANDIDATES = 8


def run_one(image_path: pathlib.Path, chain: Chain) -> dict:
    name = image_path.stem
    work_dir = OUT_DIR / name
    work_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    result = {
        "test_id": name,
        "input_image": str(image_path.relative_to(ROOT)),
        "status": "ERROR",
        "error": "",
        "faces_detected": 0,
        "detect_score": None,
        "public_image_url": "",
        "total_visual_matches": 0,
        "social_candidates": 0,
        "candidates_checked": 0,
        "best_cosine": None,
        "matched": False,
        "matched_url": "",
        "matched_title": "",
        "matched_source": "",
        "record_hash": "",
        "chain_mode": chain.mode,
        "contract_address": "",
        "anchor_tx": "",
        "anchor_verified": False,
        "elapsed_seconds": None,
    }

    try:
        # Step 1: detect + encode
        query_face = face.detect_and_embed(str(image_path))
        if query_face is None:
            result["status"] = "NO_FACE"
            result["error"] = "no face detected in input image"
            return result
        result["faces_detected"] = query_face.num_faces_detected
        result["detect_score"] = round(query_face.detect_score, 4)
        crop_path = work_dir / "face_crop.jpg"
        face.save_crop(query_face, crop_path)

        # Step 2: publish
        public_url = search.upload_public_image(crop_path)
        result["public_image_url"] = public_url

        # Step 3: search
        lens_raw = search.google_lens_search(public_url)
        (work_dir / "lens_raw.json").write_text(json.dumps(lens_raw, indent=2))
        result["total_visual_matches"] = len(lens_raw.get("visual_matches", []) or [])
        candidates = search.extract_social_candidates(lens_raw)
        result["social_candidates"] = len(candidates)

        if not candidates:
            result["status"] = "NO_SOCIAL_CANDIDATES"
            return result

        # Step 4: independently confirm
        best = None
        checked = []
        for cand in candidates[:MAX_CANDIDATES]:
            img_url = cand.get("thumbnail") or cand["link"]
            try:
                resp = requests.get(img_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                cand_face = face.detect_and_embed(resp.content)
            except Exception:
                continue
            if cand_face is None:
                continue
            score = face.cosine(query_face.embedding, cand_face.embedding)
            checked.append({"link": cand["link"], "cosine": score})
            if score >= face.SFACE_MATCH_THRESHOLD and (best is None or score > best["cosine"]):
                best = {**cand, "cosine": score}

        result["candidates_checked"] = len(checked)
        result["best_cosine"] = round(max((c["cosine"] for c in checked), default=0.0), 4)
        (work_dir / "match.json").write_text(json.dumps({"checked": checked, "match": best}, indent=2))

        if best is None:
            result["status"] = "NO_MATCH"
            return result

        result["matched"] = True
        result["matched_url"] = best["link"]
        result["matched_title"] = best.get("title", "")
        result["matched_source"] = best.get("source", "")
        result["best_cosine"] = round(best["cosine"], 4)

        # Step 5: record + anchor
        match_image_sha = record.sha256_bytes(
            requests.get(best.get("thumbnail") or best["link"], timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"}).content
        )
        match_record = {
            "query_image_sha256": record.sha256_file(str(image_path)),
            "matched_post_url": best["link"],
            "matched_post_title": best["title"],
            "matched_post_source": best.get("source", ""),
            "matched_image_sha256": match_image_sha,
            "cosine_similarity": round(best["cosine"], 6),
            "match_threshold": face.SFACE_MATCH_THRESHOLD,
            "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "test_id": name,
        }
        (work_dir / "record.json").write_text(json.dumps(match_record, indent=2, sort_keys=True))
        rhash = record.record_hash(match_record)
        result["record_hash"] = "0x" + rhash.hex()

        contract_addr = chain.deploy_or_load()
        result["contract_address"] = contract_addr
        receipt = chain.anchor(rhash, best["link"])
        result["anchor_tx"] = receipt["tx_hash"]
        (work_dir / "receipt.json").write_text(json.dumps(receipt, indent=2))

        verify_result = chain.verify(rhash)
        result["anchor_verified"] = bool(verify_result["exists"])
        result["status"] = "OK"

    except Exception as e:  # noqa: BLE001 -- batch runner must not die on one bad input
        result["status"] = "ERROR"
        result["error"] = f"{type(e).__name__}: {e}"
        traceback.print_exc(file=sys.stderr)
    finally:
        result["elapsed_seconds"] = round(time.time() - t0, 2)

    return result


def main() -> None:
    load_dotenv()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    images = sorted(BATCH_DIR.glob("*.jpg"))
    if not images:
        print("No images found in demo/batch/", file=sys.stderr)
        sys.exit(1)

    chain = Chain("local")
    chain.deploy_or_load(force_new=True)
    print(f"[batch] deployed fresh FaceRegistry at {chain.contract_address} (local chain)")

    results = []
    for i, img in enumerate(images, 1):
        print(f"\n[batch] {i}/{len(images)}: {img.name}")
        r = run_one(img, chain)
        print(f"  status={r['status']} faces={r['faces_detected']} "
              f"candidates={r['social_candidates']} best_cosine={r['best_cosine']} "
              f"matched={r['matched']} anchored={r['anchor_verified']}")
        results.append(r)

    RESULTS_PATH.write_text(json.dumps(results, indent=2))
    print(f"\n[batch] wrote {len(results)} results -> {RESULTS_PATH}")

    ok = sum(1 for r in results if r["status"] == "OK")
    print(f"[batch] summary: {ok}/{len(results)} OK, "
          f"{sum(1 for r in results if r['status']=='NO_MATCH')} no-match, "
          f"{sum(1 for r in results if r['status']=='NO_FACE')} no-face, "
          f"{sum(1 for r in results if r['status']=='NO_SOCIAL_CANDIDATES')} no-social-candidates, "
          f"{sum(1 for r in results if r['status']=='ERROR')} error")


if __name__ == "__main__":
    main()
