# Recording script (no frontend needed)

Everything is provable from a terminal + a browser. Judges don't need a UI — they need to see
**real network calls happening live** and **independently confirm the result on sites you don't
control** (Instagram, PolygonScan). That's actually more convincing than a UI would be.

## Setup before you hit record

- Terminal: large font (18-20pt), dark theme, maximized. `cd hhgoa-faceid-chain`, venv activated.
- Browser: one tab ready, address bar visible.
- Screen recorder: Windows Game Bar (`Win+G` → capture widget → record) or OBS. Record the whole
  screen or just the terminal+browser window — either is fine, task says "no editing needed."
- Have `.env` filled in (`SERPAPI_API_KEY`, `PRIVATE_KEY`, `AMOY_RPC_URL`) and confirm your Amoy
  wallet still has gas: `python -c "from web3 import Web3; w3=Web3(Web3.HTTPProvider('https://polygon-amoy-bor-rpc.publicnode.com')); print(w3.from_wei(w3.eth.get_balance('0x94edF6823d01f01A06eFD45f72DB0A5FdfF0c692'),'ether'))"`

## The recording (≈3-4 minutes, one continuous take)

**1. Show the input (10s)**
Open `demo/input_face.jpg` in an image viewer for a second, or just say out loud "this is the
input photo, a face scan." No narration needed on faked "scanning" — the photo is the scan.

**2. Run the real pipeline live (60-90s)**
```
python -m faceid.run --image demo/input_face.jpg --chain amoy
```
Let it print live. This is the whole story in one command — narrate along with the `[run]` lines
as they appear:
- Step 1: "detecting and encoding the face" — point out the detect score and bbox.
- Step 2: "uploading the crop publicly so a search engine can reach it" — read out the URL.
- Step 3: "genuine Google Lens reverse-image search, right now, not cached" — point out
  "N total visual matches" — this number is different every run, which is the proof it's live.
- Step 4: "independently re-verifying every candidate by re-downloading it and comparing face
  embeddings" — the cosine scores scroll by live.
- Step 5: "hashing the match and anchoring on Polygon Amoy" — the tx hash prints.

**3. Prove the match is real (30s)**
Copy the `matched_post_url` the run just printed. Paste it into the browser. Show the actual
Instagram/X/whatever post next to the input photo — same face, real account, real post. This is
the moment that proves step 3 wasn't hardcoded.

**4. Prove the blockchain record is real (30s)**
Paste the `explorer_tx_url` the run printed into the browser →
`amoy.polygonscan.com/tx/<hash>` — show Status: Success, real block number, real gas fee, the
`Anchor` function call. This is a public record you don't control; anyone can pull this URL up
independently.

**4b. Show the verification certificate (15s)**
Open `out/07_certificate.png` — the input face next to the matched image, the cosine score, the
record hash, the tx hash, and a QR code that scans straight to the same PolygonScan tx. A
one-glance summary of everything the last two steps just proved manually. If `PINATA_JWT` is
configured, mention that the full record is also permanently pinned on IPFS (visible in
`out/06_receipt.json`'s `ipfs_cid`/`ipfs_gateway_url`, and folded into the on-chain `uri` itself)
— so even if the original post is deleted, the discovered data stays independently inspectable.

**5. Independent re-verification (30s)**
```
python -m faceid.verify --chain amoy --record out/05_record.json
```
Narrate: "this re-reads the record from disk, recomputes the hash from scratch, and asks the
chain if it matches — MATCH, with the same tx data." Then:
```
python -m faceid.verify --chain amoy --record out/05_record.json --tamper
```
Narrate: "if I alter even one number in that record and ask again — NO RECORD ON CHAIN. That's
the tamper-evidence: the chain only recognizes the exact original data."

**6. (Optional, if time allows) Show the batch evidence (20s)**
Open `out/batch_test_results.xlsx` — "we ran this pipeline end-to-end on 22 different people,
21 matched and anchored, one was honestly rejected below the similarity threshold instead of
faking a match." Scroll the sheet briefly.

**7. Close (10s)**
"Full source, README, and this spreadsheet are all in the GitHub repo." Show the repo page for a
second if you like.

## If something flakes during the take

- SerpAPI/network hiccup → just re-run step 2's command; it's idempotent (new record each time).
- Low on Amoy gas → fall back to `--chain local` for the live run, then show the *already-anchored*
  Amoy tx from an earlier run (`out/06_receipt.json` / the PolygonScan link) as proof that part
  works, narrating "and here's a real Amoy anchor from an earlier run of this exact code."
- Don't restart the whole recording for a single hiccup — task says no editing needed, but a clean
  cut/restart of the terminal segment is fine if your recorder supports trimming.
