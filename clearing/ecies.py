"""ECIES seal/unseal for order bundles.

Agents encrypt order bundles to the enclave's secp256k1 public key.
Uses eciespy for ECIES (secp256k1 + AES-256-GCM).
"""
from __future__ import annotations

import hashlib
import json
from typing import List

from .types import Order


def seal_bundle(
    orders: List[Order],
    enclave_pubkey_hex: str,
    round_id: str,
    agent_id: str,
    nonce_hex: str,
) -> bytes:
    """ECIES-encrypt an order bundle to the enclave's public key.

    Returns ciphertext bytes. The commitment hash is SHA-256(ciphertext).
    """
    import ecies

    plaintext = json.dumps({
        "round_id": round_id,
        "agent_id": agent_id,
        "nonce": nonce_hex,
        "orders": [o.model_dump(mode="json") for o in orders],
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")

    pubkey = enclave_pubkey_hex
    if pubkey.startswith("0x"):
        pubkey = pubkey[2:]

    ciphertext = ecies.encrypt(pubkey, plaintext)
    return ciphertext


def unseal_bundle(ciphertext: bytes, enclave_privkey_hex: str) -> dict:
    """ECIES-decrypt an order bundle using the enclave's private key.

    Returns the parsed order bundle dict with keys:
      round_id, agent_id, nonce, orders
    """
    import ecies

    privkey = enclave_privkey_hex
    if privkey.startswith("0x"):
        privkey = privkey[2:]

    plaintext = ecies.decrypt(privkey, ciphertext)
    return json.loads(plaintext.decode("utf-8"))


def commitment_hash(ciphertext: bytes) -> str:
    """SHA-256 of ciphertext, used as the commitment in commit-reveal."""
    return hashlib.sha256(ciphertext).hexdigest()
