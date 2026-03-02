"""Shared setup for quoting-engine-powered strategies.

Adds the Tee-work- paths to sys.path so quoting_engine and
risk_multipliers are importable without pip install.
"""
from __future__ import annotations

import os
import sys

# Add Tee-work- repo root + quoting_engine package to sys.path
_TEE_ROOT = os.path.expanduser("~/Tee-work-")
_QE_ROOT = os.path.join(_TEE_ROOT, "quoting_engine")

for p in [_TEE_ROOT, _QE_ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)
