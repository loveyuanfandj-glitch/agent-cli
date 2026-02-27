"""Cryptographic utilities — secp256k1 via eth-account."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from eth_account import Account
from eth_account.messages import encode_defunct


@dataclass
class KeyPair:
    private_key_hex: str
    address: str


def generate_secp256k1_keypair(entropy: bytes | None = None) -> KeyPair:
    if entropy is None:
        entropy = os.urandom(32)
    acct = Account.from_key(entropy)
    return KeyPair(private_key_hex=acct.key.hex(), address=acct.address)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sign_hash_hex(hash_hex: str, private_key_hex: str) -> str:
    msg = encode_defunct(hexstr=hash_hex)
    signed = Account.sign_message(msg, private_key=bytes.fromhex(private_key_hex))
    return "0x" + signed.signature.hex()


def pubkey_to_address(pubkey_hex: str) -> str:
    """Convert uncompressed public key (0x04...) to Ethereum address."""
    from eth_keys import keys as eth_keys_mod
    raw = pubkey_hex.replace("0x", "")
    if raw.startswith("04") and len(raw) == 130:
        raw = raw[2:]
    pub = eth_keys_mod.PublicKey(bytes.fromhex(raw))
    return pub.to_checksum_address()


def verify_signature(hash_hex: str, signature_hex: str, expected_key: str) -> bool:
    """Verify ECDSA signature. expected_key can be an address or public key."""
    msg = encode_defunct(hexstr=hash_hex)
    try:
        recovered = Account.recover_message(msg, signature=signature_hex)
        clean = expected_key.replace("0x", "")
        if len(clean) > 42:
            expected_addr = pubkey_to_address(expected_key)
        else:
            expected_addr = expected_key
        return recovered.lower() == expected_addr.lower()
    except Exception:
        return False
