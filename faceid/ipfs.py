"""Optional: pin the full match record JSON to IPFS via Pinata, so a
permanent, content-addressed copy of "the discovered data" survives even if
the original social post is later deleted.

Purely additive and optional: if PINATA_JWT is not set in the environment,
is_configured() returns False and callers should fall back to their existing
behavior unchanged. Sign up free at https://pinata.cloud -> API Keys -> New
Key -> copy the JWT.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import requests

PINATA_PIN_JSON_URL = "https://api.pinata.cloud/pinning/pinJSONToIPFS"
IPFS_GATEWAY = "https://gateway.pinata.cloud/ipfs/{cid}"


class IPFSError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(os.environ.get("PINATA_JWT"))


def pin_record(match_record: dict[str, Any], *, name: str = "faceid-match-record") -> Optional[str]:
    """Pins match_record as JSON to IPFS via Pinata. Returns the CID, or None
    if PINATA_JWT isn't set. Raises IPFSError on an API failure.
    """
    jwt = os.environ.get("PINATA_JWT")
    if not jwt:
        return None
    resp = requests.post(
        PINATA_PIN_JSON_URL,
        headers={"Authorization": f"Bearer {jwt}"},
        json={"pinataContent": match_record, "pinataMetadata": {"name": name}},
        timeout=30,
    )
    if not resp.ok:
        raise IPFSError(f"Pinata pin failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json()["IpfsHash"]


def gateway_url(cid: str) -> str:
    return IPFS_GATEWAY.format(cid=cid)
