# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A pipeline that takes a face photo, finds a real matching social media post via a genuine
reverse-image search, and anchors that discovery on a public blockchain (Polygon Amoy testnet, or
a local in-process EVM) as a tamper-evident record. Built for a hackathon submission — see
`README.md` for the full pipeline description, blockchain details, and known limitations.

## Setup and common commands

```bash
python -m venv venv
venv\Scripts\activate                  # Windows
pip install -r requirements.txt
python -m faceid.models                # one-time: downloads YuNet + SFace ONNX models into models/
```

Copy `.env.example` to `.env` and fill in `SERPAPI_API_KEY` (required), `PRIVATE_KEY` (only for
`--chain amoy`, generate a throwaway wallet with `python scripts/new_wallet.py` then fund it from
the Polygon Amoy faucet), and optionally `PINATA_JWT` (see Bonus features below).

Run the full pipeline:
```bash
python -m faceid.run --image demo/input_face.jpg --chain local   # free, no network chain needed
python -m faceid.run --image demo/input_face.jpg --chain amoy    # real testnet anchor, costs gas
```

Re-verify a previously anchored record (standalone, works any time after, from any machine — but
only reliably against `--chain amoy`, see Architecture below):
```bash
python -m faceid.verify --chain amoy --record out/05_record.json
python -m faceid.verify --chain amoy --record out/05_record.json --tamper   # tamper-evidence demo
```

Batch QA over 22 public-figure photos (local chain only, no gas cost):
```bash
python scripts/fetch_batch_images.py
python scripts/batch_test.py
python scripts/make_excel_report.py    # requires openpyxl; builds out/batch_test_results.xlsx
```

There is no lint/test-runner config (no pytest, no linter) — correctness is verified by actually
running the pipeline end-to-end and inspecting the numbered `out/*.json` artifacts each step
produces, or by running `scripts/batch_test.py` across many inputs.

**Windows-only gotcha**: `eth-tester[py-evm]` (needed for `--chain local`) depends on
`safe-pysha3`, which has no prebuilt Windows wheel and needs an actual C/C++ compiler (e.g.
Microsoft C++ Build Tools) to build from source. `--chain amoy` has no such requirement.

## Architecture

`faceid/run.py` is the entry point and owns the whole control flow as 5 sequential steps, each
writing a numbered artifact to `out/` so every step is independently inspectable:

1. **Detect + embed** (`faceid/face.py`) — OpenCV YuNet detects the face, OpenCV SFace produces a
   128-d embedding (`SFACE_MATCH_THRESHOLD = 0.363` is the "same person" cosine cutoff used later).
2. **Publish the crop publicly** (`faceid/search.py: upload_public_image`) — tries a chain of free
   anonymous image hosts (catbox.moe → tmpfiles.org → litterbox → 0x0.st) since Google Lens needs
   a public URL, not raw bytes.
3. **Reverse-image search** (`faceid/search.py: google_lens_search` + `extract_social_candidates`)
   — a real SerpAPI Google Lens call, filtered down to a fixed allow-list of social platform hosts
   (`SOCIAL_HOSTS`). The raw response is persisted verbatim so the search is auditable.
4. **Independently re-verify candidates** (back in `run.py`, using `face.py`) — re-downloads each
   candidate's `thumbnail` (never falls back to the webpage `link` — a candidate missing a
   thumbnail is skipped with an explicit `skipped_reason`, not silently mis-decoded) and re-embeds
   it, picking the highest-cosine match above threshold. The winning candidate's image bytes are
   captured in `best_image_bytes` right here and reused later — never re-fetched.
5. **Build the record + anchor on-chain** (`faceid/record.py` + `faceid/chain.py`) — a canonical
   JSON record (sorted keys, compact separators) is keccak256-hashed via `record.record_hash()`;
   `Chain.anchor(record_hash, uri)` calls the deployed `FaceRegistry.sol` contract
   (`anchor(bytes32,string)` / `verify(bytes32) -> (bool,uint64,address,string)`).

`faceid/chain.py`'s `Chain` class wraps two very different modes:
- `"local"`: an in-process `eth-tester` EVM. `deploy_or_load()` **always** force-redeploys in this
  mode, because eth-tester's state is purely in-memory and dies with the Python process — a cached
  `out/deployment_local.json` address would never have code on a fresh instance. This is why
  `faceid/verify.py` run as a separate process against `--chain local` will always report "NO
  RECORD ON CHAIN" even for a valid record — expected behavior, not a bug (see the module
  docstring). `run.py` demonstrates the verify+tamper story in-process instead when `--chain local`.
- `"amoy"`: real Polygon Amoy testnet via `AMOY_RPC_URL`/`PRIVATE_KEY`. `deploy_or_load()` reuses
  the cached `out/deployment_amoy.json` address across runs as long as the address still has code
  on-chain — so most runs only pay anchor gas, not redeploy gas. Each mode has its own cache file
  precisely so a `--chain local` rehearsal can never overwrite the cached `--chain amoy` contract
  address (see `chain.py: _deployment_file()`).

Both `run.py` and `scripts/batch_test.py` independently implement the same 5-step logic against
`faceid/*` (batch_test.py doesn't import run.py) — a fix to the candidate-matching logic in one
generally needs to be mirrored in the other.

### Bonus features (all optional, purely additive, called from `run.py` only)

Three modules extend `run.py` without touching its Steps 1-5 logic; each is wrapped in its own
try/except at the call site so a failure never changes the core pipeline's exit code:
- `faceid/certificate.py` — renders `out/07_certificate.png` (input face vs. matched image, score,
  hashes, and a QR to the explorer tx — or a "no public explorer" placeholder on `--chain local`).
- `faceid/ipfs.py` — if `PINATA_JWT` is set, pins the full match-record JSON to IPFS via Pinata's
  `pinJSONToIPFS` REST endpoint and folds the CID into the on-chain `uri` string
  (`<post url> | ipfs://<cid>`); if unset, `uri` is just the post link, unchanged from before this
  feature existed.
- `faceid/console.py` — shared `rich`-based logging (`log()`/`rule()`/`spinner()`) used by both
  `run.py` and `verify.py`; the underlying plaintext content of every log line is unchanged from
  plain `print()`, only styling is added.
