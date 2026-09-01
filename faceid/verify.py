"""Independently re-verify a match record against the on-chain FaceRegistry.

Usage:
    python -m faceid.verify --chain local --record out/05_record.json
    python -m faceid.verify --chain amoy  --record out/05_record.json
    python -m faceid.verify --chain amoy  --record out/05_record.json --tamper

--tamper mutates one field of the record in memory (simulating someone
altering the "discovered data" after the fact) and re-runs verification,
to demonstrate the anchor is tamper-evident: the recomputed hash no longer
matches anything on-chain.
"""
from __future__ import annotations

import argparse
import io
import json
import pathlib
import sys

from dotenv import load_dotenv

# Windows terminals often default stdout/stderr to a legacy codepage (cp1252)
# that can't encode checkmark/cross characters -- force UTF-8 so the output
# is safe to print (and to redirect to a file) on any platform.
if sys.stdout.encoding is None or sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding is None or sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from . import record
from .chain import Chain


def log(msg: str) -> None:
    print(f"[verify] {msg}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True, help="Path to a 05_record.json produced by run.py")
    parser.add_argument("--chain", choices=["local", "amoy"], default="local")
    parser.add_argument(
        "--tamper", action="store_true",
        help="Flip the cosine_similarity value before verifying, to demonstrate a "
             "tampered record fails on-chain verification",
    )
    args = parser.parse_args()

    load_dotenv()

    rec_path = pathlib.Path(args.record)
    rec = json.loads(rec_path.read_text())

    if args.tamper:
        original = rec.get("cosine_similarity", 0.0)
        rec["cosine_similarity"] = round(original + 0.05, 6)
        log(f"--tamper: mutated cosine_similarity {original} -> {rec['cosine_similarity']}")

    rhash = record.record_hash(rec)
    log(f"recomputed record hash: 0x{rhash.hex()}")

    chain = Chain(args.chain)
    chain.deploy_or_load()  # loads the cached deployment; does not redeploy
    result = chain.verify(rhash)

    print(json.dumps({"record_hash": "0x" + rhash.hex(), **result}, indent=2))

    if result["exists"]:
        print(f"\nMATCH ✅  anchored at unix ts={result['timestamp']} by {result['submitter']}")
        print(f"          uri: {result['uri']}")
        return 0
    else:
        print("\nNO RECORD ON CHAIN ❌  -- this exact data does not match any anchored record "
              "(data has been altered, or was never anchored).")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
