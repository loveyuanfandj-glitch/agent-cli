"""Model Registry — versioned strategy bundles with source-code hashing.

Registers strategies by hashing their actual Python source code via
inspect.getsource(), storing bundles in a JSONL file for audit and
reproducibility.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from common.crypto import canonical_json_bytes, sha256_hex
from sdk.strategy_sdk.loader import load_strategy

log = logging.getLogger("model_registry")


@dataclass
class StrategyBundle:
    strategy_id: str
    module_path: str          # e.g. "strategies.avellaneda_mm:AvellanedaStoikovMM"
    source_hash: str          # SHA-256 of inspect.getsource(cls)
    params: Dict[str, Any] = field(default_factory=dict)
    registered_at: str = ""   # ISO timestamp
    signature: str = ""       # optional secp256k1 signature


def hash_strategy_source(cls: type) -> str:
    """Compute SHA-256 hash of a strategy class's source code."""
    source = inspect.getsource(cls)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def compute_bundle_hash(module_path: str, params: Optional[Dict] = None) -> str:
    """Load a strategy class and compute its source hash.

    Returns the SHA-256 of the class source + params.
    Falls back to module_path hash if the class cannot be loaded.
    """
    try:
        cls = load_strategy(module_path)
        source_hash = hash_strategy_source(cls)
    except Exception as e:
        log.warning("Cannot load %s for hashing: %s — using path hash", module_path, e)
        source_hash = sha256_hex(module_path.encode("utf-8"))

    bundle = {"source_hash": source_hash, "params": params or {}}
    return sha256_hex(canonical_json_bytes(bundle))


class ModelRegistry:
    """JSONL-backed registry of strategy bundles."""

    def __init__(self, path: str = "artifacts/registry.jsonl"):
        self.path = path
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)

    def register(self, module_path: str, params: Optional[Dict] = None) -> StrategyBundle:
        """Load strategy class, hash source, store bundle. Returns the bundle."""
        cls = load_strategy(module_path)
        source_hash = hash_strategy_source(cls)
        strategy_id = cls.__name__

        bundle = StrategyBundle(
            strategy_id=strategy_id,
            module_path=module_path,
            source_hash=source_hash,
            params=params or {},
            registered_at=datetime.now(timezone.utc).isoformat(),
        )

        with open(self.path, "a") as f:
            f.write(json.dumps(asdict(bundle), sort_keys=True) + "\n")

        log.info("Registered %s (hash=%s...%s)", strategy_id,
                 source_hash[:10], source_hash[-6:])
        return bundle

    def verify(self, bundle: StrategyBundle) -> bool:
        """Re-hash source and compare to stored hash."""
        try:
            cls = load_strategy(bundle.module_path)
            current_hash = hash_strategy_source(cls)
            return current_hash == bundle.source_hash
        except Exception:
            return False

    def get(self, strategy_id: str) -> Optional[StrategyBundle]:
        """Lookup latest bundle for a strategy (by class name)."""
        if not os.path.exists(self.path):
            return None
        latest = None
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if data.get("strategy_id") == strategy_id:
                    latest = StrategyBundle(**data)
        return latest

    def list_all(self) -> List[StrategyBundle]:
        """List all registered bundles (latest per strategy)."""
        if not os.path.exists(self.path):
            return []
        seen: Dict[str, StrategyBundle] = {}
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                bundle = StrategyBundle(**data)
                seen[bundle.strategy_id] = bundle
        return list(seen.values())
