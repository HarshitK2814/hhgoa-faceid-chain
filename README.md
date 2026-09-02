# Face ID → Social Search → Blockchain Anchor

A pipeline that takes a face photo, finds a **real** matching social media post via a genuine
reverse-image search, and anchors that discovery on a public blockchain as a tamper-evident
record — end to end, no hardcoded results.

```
face photo -> detect + encode face -> reverse-image search (Google Lens) -> genuine social match
           -> independently re-verify match by face embedding -> hash the record -> anchor on-chain
```

> **Security note:** all credentials (`SERPAPI_API_KEY`, `PRIVATE_KEY`, `AMOY_RPC_URL`) live in a
> gitignored `.env` file, never in source. The demo wallet is a disposable Polygon Amoy **testnet**
> key generated with `scripts/new_wallet.py` — it holds no mainnet value and should never be reused
> for a real wallet.

## What it does

1. **Face detection + encoding** — [OpenCV YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
   detects the face, [OpenCV SFace](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface)
   produces a 128-d embedding.
2. **Genuine reverse-image search** — the aligned face crop is uploaded to a public temp image
   host, then searched with [SerpAPI's Google Lens engine](https://serpapi.com/google-lens-api).
   The **entire raw API response** is saved to `out/03_lens_raw.json` so the search is auditable —
   nothing is cached or pre-picked.
3. **Filter + independently confirm the match** — results are filtered to recognized social
   platforms (Instagram, X, Facebook, LinkedIn, TikTok, YouTube, Reddit, Pinterest, Threads), then
   each candidate image is **re-downloaded and re-encoded** and compared to the query face by
   cosine similarity (threshold 0.363, OpenCV's documented SFace default). The pipeline does not
   just trust Google Lens's ranking — it verifies the match itself. If nothing passes the
   threshold, the run stops honestly with no match, and nothing is anchored.
4. **Blockchain anchor** — a minimal `FaceRegistry` Solidity contract stores `keccak256(canonical
   JSON record) -> {timestamp, submitter, uri}`. The record includes the query image hash, the
   embedding hash, the matched post URL, the matched image hash, the cosine score, and a
   timestamp. Anchoring the same hash twice reverts (tamper-evidence: no silent overwrite).
5. **Re-verification** — `faceid/verify.py` independently recomputes the hash from the saved
   record file and calls the contract's `verify()` view function. A `--tamper` flag mutates one
   field first, to demonstrate that altered data no longer matches anything on-chain.

## Blockchain used

**Polygon Amoy** (public EVM testnet, chain id 80002) — real transactions, viewable on
[amoy.polygonscan.com](https://amoy.polygonscan.com). Example from this repo's own test run:
- Deployment: [`0x832298598FD7A8066C7f30ba43B38050b3Fb70F8`](https://amoy.polygonscan.com/address/0x832298598FD7A8066C7f30ba43B38050b3Fb70F8)
- Anchor tx: [`0x77d6ee91bfc991118bbb772a397d3c97781100eaccfbd4d802b47bd458841ed8`](https://amoy.polygonscan.com/tx/0x77d6ee91bfc991118bbb772a397d3c97781100eaccfbd4d802b47bd458841ed8)

A `--chain local` mode is also included: an in-process EVM ([eth-tester](https://github.com/ethereum/eth-tester))
that needs no network access or funded wallet, used for fast development/testing of the same
contract and code path. Its state is process-local (doesn't persist across separate runs), so
`run.py --chain local` demonstrates the verify+tamper check in the same process; for a persistent,
independently re-checkable record (e.g. from a different machine, days later), use `--chain amoy`.

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
python -m faceid.models        # downloads the two ONNX models (~39MB total, one-time)
```

Copy `.env.example` to `.env` and fill in:

```
SERPAPI_API_KEY=...            # https://serpapi.com/manage-api-key (free tier: 100/mo)
AMOY_RPC_URL=https://polygon-amoy-bor-rpc.publicnode.com
PRIVATE_KEY=...                # only needed for --chain amoy, see below
```

### Funding a wallet for `--chain amoy`

```bash
python scripts/new_wallet.py   # generates a throwaway keypair, prints address + private key
```
Fund the printed address with free testnet POL from the
[Polygon faucet](https://faucet.polygon.technology) (select Amoy; requires a GitHub/X login to
rate-limit requests — this is Polygon's faucet policy, not ours). Put the private key in `.env`.
**Never reuse this key for a real wallet.**

## Running it

```bash
# Fast path, no external chain / wallet needed:
python -m faceid.run --image demo/input_face.jpg --chain local

# Real testnet anchor (needs SERPAPI_API_KEY + funded PRIVATE_KEY):
python -m faceid.run --image demo/input_face.jpg --chain amoy

# Re-verify a previously anchored record (works standalone, any time after):
python -m faceid.verify --chain amoy --record out/05_record.json

# Demonstrate tamper-evidence: mutate the record and show it no longer verifies
python -m faceid.verify --chain amoy --record out/05_record.json --tamper
```

Every run writes numbered artifacts to `out/` so each step is inspectable after the fact:

| File | Contents |
|---|---|
| `01_face_crop.jpg` | the aligned face crop used for search + embedding |
| `02_embedding.json` | the 128-d face embedding + its sha256 |
| `03_lens_raw.json` | **the full, raw SerpAPI Google Lens response** — proof the search was genuine |
| `04_match.json` | every candidate checked, its cosine score, and the winning match |
| `05_record.json` | the canonical record that got hashed and anchored |
| `06_receipt.json` | tx hash, block number, contract address, explorer link |
| `deployment.json` | cached contract address + ABI, reused across runs on the same chain |

## Repo layout

```
faceid/
  models.py   # downloads/caches the YuNet + SFace ONNX models
  face.py     # detect_and_embed(), cosine() -- face detection + embedding
  search.py   # upload_public_image(), google_lens_search(), extract_social_candidates()
  record.py   # canonical JSON + keccak256 hashing
  chain.py    # compiles FaceRegistry.sol, deploys, anchor()/verify() on local or Amoy
  run.py      # end-to-end CLI (steps 1-5 above)
  verify.py   # standalone re-verification CLI (+ --tamper demo)
contracts/
  FaceRegistry.sol
scripts/
  new_wallet.py   # generates a throwaway Amoy wallet
demo/
  input_face.jpg  # sample public-figure photo used in the recorded demo
```

## Batch test results

`scripts/batch_test.py` runs the full pipeline (face detect → search → independently re-verify
match → hash → anchor → re-verify on-chain) over 22 public-figure photos (`demo/batch/`) on the
local chain, and writes a row per test to
[`out/batch_test_results.xlsx`](out/batch_test_results.xlsx) (raw data in
`out/batch_test_results.json`). Latest run: **21/22 matched and anchored**, 1 honest "no match"
(threshold correctly rejected a low-confidence candidate), 0 errors, average cosine similarity
0.847 across matches.

> Note: these 22 anchors run on `--chain local` (see [Known limitations](#known-limitations))
> and therefore exist only inside now-destroyed in-process EVM instances — they are not
> independently checkable on a public explorer the way the single `--chain amoy` example
> above is. This batch is evidence of pipeline *correctness/repeatability* across many faces,
> not of *on-chain persistence* (which the Amoy example above already demonstrates).

Reproduce with:

```bash
python scripts/fetch_batch_images.py   # downloads the 22 demo photos (Wikipedia)
python scripts/batch_test.py           # runs the pipeline on all of them, local chain
python scripts/make_excel_report.py    # builds out/batch_test_results.xlsx
```

## Known limitations

- **Similarity, not identification.** SFace cosine similarity (threshold 0.363, OpenCV's
  documented default) will produce false positives on lookalikes, low-resolution crops, or
  heavy filters/editing, and false negatives on extreme angles/aging. It is not a legal identity
  claim.
- **Search coverage depends on public indexing.** Google Lens only surfaces images it has
  crawled. A private individual, or someone with no publicly indexed photos, will correctly
  produce "no match found" rather than a fabricated result — this is by design, not a bug.
- **SerpAPI free tier** is rate-limited (100–250 searches/month depending on plan). Each `run.py`
  invocation uses exactly one search call.
- **Temporary image hosting.** The face crop is uploaded to a free anonymous host (catbox.moe,
  with tmpfiles.org/0x0.st/litterbox.catbox.moe as fallbacks) purely so Google Lens can fetch it
  by URL; the on-chain record stores content hashes, not that temporary URL.
- **Testnet, not mainnet.** Polygon Amoy has no economic finality guarantee — it demonstrates the
  tamper-evident/public-audit mechanism, not custody of real value. Swapping to a mainnet is a
  one-line RPC/chain-id change in `chain.py`.
- **`--chain local` is process-local.** eth-tester's in-memory EVM doesn't persist across separate
  script invocations, so a later `verify.py` call against `--chain local` won't find a contract
  deployed in an earlier process. Use `--chain amoy` for verification that needs to survive across
  runs, machines, or time.
- **`--chain local` needs a C/C++ compiler on Windows.** `eth-tester[py-evm]`'s `safe-pysha3`
  dependency has no prebuilt Windows wheel, so `pip install -r requirements.txt` will fail to build
  it unless a compiler is available (e.g. Microsoft C++ Build Tools). This only affects the local
  in-process chain — `--chain amoy` (the graded/demo path) has no such requirement.
- **Ethical scope.** This is a hackathon demonstration of a face-search + verification pipeline,
  not a surveillance tool. The demo uses a public figure's publicly available photo.
