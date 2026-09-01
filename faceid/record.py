"""Canonical JSON record + hashing helpers shared by run.py and verify.py.

The "record" is the piece of evidence we anchor on-chain: everything a
third party needs to independently confirm the pipeline actually found
a real match, without needing to re-run the search itself. We hash a
*canonical* JSON encoding (sorted keys, no whitespace) with keccak256
so the same dict always produces the same bytes32, which is what
FaceRegistry.sol stores.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from web3 import Web3


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    with open(path, "rb") as f:
        return sha256_bytes(f.read())


def canonical_json(record: Mapping[str, Any]) -> bytes:
    """Deterministic byte encoding of a record dict."""
    return json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")


def record_hash(record: Mapping[str, Any]) -> bytes:
    """keccak256 of the canonical JSON encoding -> 32 bytes, for bytes32 on-chain."""
    return Web3.keccak(canonical_json(record))


def record_hash_hex(record: Mapping[str, Any]) -> str:
    return "0x" + record_hash(record).hex()
