"""Download a diverse set of public-figure photos (via Wikipedia's pageimages
API, which reliably returns a single portrait thumbnail per title) for the
batch test run. These are used purely as demo inputs -- publicly available
photos of public figures, same rationale as demo/input_face.jpg.
"""
from __future__ import annotations

import pathlib
import time

import requests

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "demo" / "batch"

NAMES = [
    "Barack Obama",
    "Elon Musk",
    "Taylor Swift",
    "Cristiano Ronaldo",
    "Lionel Messi",
    "Dwayne Johnson",
    "Oprah Winfrey",
    "Rihanna",
    "Tom Cruise",
    "Emma Watson",
    "Narendra Modi",
    "Priyanka Chopra",
    "Shah Rukh Khan",
    "Virat Kohli",
    "Selena Gomez",
    "Justin Bieber",
    "Beyonce Knowles",
    "Leonardo DiCaprio",
    "Kim Kardashian",
    "Serena Williams",
    "Roger Federer",
    "Angelina Jolie",
    "Will Smith",
]

UA = "hhgoa-faceid-chain-batch-test/1.0 (educational hackathon demo)"


def fetch_thumbnail_url(title: str) -> str | None:
    resp = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "titles": title,
            "prop": "pageimages",
            "format": "json",
            "pithumbsize": 800,
        },
        headers={"User-Agent": UA},
        timeout=20,
    )
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    for page in pages.values():
        thumb = page.get("thumbnail", {}).get("source")
        if thumb:
            return thumb
    return None


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, name in enumerate(NAMES, 1):
        slug = name.lower().replace(" ", "_")
        dest = OUT_DIR / f"{i:02d}_{slug}.jpg"
        if dest.exists():
            manifest.append((name, dest))
            continue
        try:
            url = fetch_thumbnail_url(name)
            if not url:
                print(f"  SKIP {name}: no thumbnail found")
                continue
            img = requests.get(url, headers={"User-Agent": UA}, timeout=20)
            img.raise_for_status()
            dest.write_bytes(img.content)
            print(f"  OK   {name} -> {dest.name} ({len(img.content)} bytes)")
            manifest.append((name, dest))
        except Exception as e:
            print(f"  FAIL {name}: {e}")
        time.sleep(2)

    print(f"\n{len(manifest)}/{len(NAMES)} images ready in {OUT_DIR}")


if __name__ == "__main__":
    main()
