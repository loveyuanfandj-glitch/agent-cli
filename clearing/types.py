"""Data types for the batch clearing engine."""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Order(BaseModel):
    agent_id: str
    instrument: str
    side: str  # "buy" or "sell"
    price: Decimal
    quantity: Decimal
    order_idx: int = 0  # position within agent's bundle (for KKT indexing)

    class Config:
        json_encoders = {Decimal: str}


class Fill(BaseModel):
    agent_id: str
    instrument: str
    side: str
    original_price: Decimal
    quantity_requested: Decimal
    quantity_filled: Decimal
    fill_price: Decimal

    class Config:
        json_encoders = {Decimal: str}


class KKTCertificate(BaseModel):
    lambda_val: Decimal
    mu_buy: List[Dict]   # [{"order_idx": int, "mu": Decimal}, ...]
    mu_sell: List[Dict]
    total_surplus: Decimal

    class Config:
        json_encoders = {Decimal: str}


class InstrumentResult(BaseModel):
    clearing_price: Decimal
    total_volume: Decimal
    num_buy_fills: int
    num_sell_fills: int

    class Config:
        json_encoders = {Decimal: str}


class RoundMetadata(BaseModel):
    num_agents: int
    num_committed: int
    num_revealed: int
    no_shows: List[str] = Field(default_factory=list)
    submission_deadline_ms: int = 0
    clearing_timestamp_ms: int = 0


class ClearingResult(BaseModel):
    round_id: str
    instruments: Dict[str, InstrumentResult]
    fills: List[Fill]
    kkt_certificates: Dict[str, KKTCertificate]
    round_metadata: RoundMetadata
    agent_public_key: str = ""
    timestamp: str = ""
    nonce: str = ""

    class Config:
        json_encoders = {Decimal: str}


class RoundConfig(BaseModel):
    round_id: str
    instruments: List[str]
    submission_deadline_ms: int
    reveal_window_ms: int = 5000
    agent_whitelist: Optional[List[str]] = None


class SealedBundle(BaseModel):
    agent_id: str
    commitment_hash: str
    ciphertext: Optional[bytes] = None
    revealed: bool = False

    class Config:
        json_encoders = {bytes: lambda v: v.hex() if v else None}
