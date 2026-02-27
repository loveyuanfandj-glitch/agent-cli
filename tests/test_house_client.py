"""Tests for house enclave client — clearing types, ECIES, strategy adapter, registry."""
import os
import sys
import tempfile
from decimal import Decimal

import pytest

# Ensure project root is importable
_root = str(os.path.join(os.path.dirname(__file__), ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)


# ---------------------------------------------------------------------------
# Clearing types
# ---------------------------------------------------------------------------

class TestClearingTypes:
    def test_order_creation(self):
        from clearing.types import Order
        o = Order(
            agent_id="agent-1",
            instrument="ETH-PERP",
            side="buy",
            price=Decimal("2500.00"),
            quantity=Decimal("0.5"),
            order_idx=0,
        )
        assert o.agent_id == "agent-1"
        assert o.price == Decimal("2500.00")
        assert o.quantity == Decimal("0.5")

    def test_order_json_roundtrip(self):
        from clearing.types import Order
        o = Order(
            agent_id="a1", instrument="SOL-PERP", side="sell",
            price=Decimal("150.50"), quantity=Decimal("10"),
        )
        data = o.model_dump(mode="json")
        assert data["price"] == "150.50"
        o2 = Order(**data)
        assert o2.price == Decimal("150.50")

    def test_fill_creation(self):
        from clearing.types import Fill
        f = Fill(
            agent_id="a1", instrument="ETH-PERP", side="buy",
            original_price=Decimal("2500"), quantity_requested=Decimal("1"),
            quantity_filled=Decimal("0.8"), fill_price=Decimal("2495"),
        )
        assert f.quantity_filled == Decimal("0.8")

    def test_clearing_result_creation(self):
        from clearing.types import (
            ClearingResult, InstrumentResult, Fill,
            KKTCertificate, RoundMetadata,
        )
        result = ClearingResult(
            round_id="r-001",
            instruments={
                "ETH-PERP": InstrumentResult(
                    clearing_price=Decimal("2500"),
                    total_volume=Decimal("10"),
                    num_buy_fills=3,
                    num_sell_fills=2,
                ),
            },
            fills=[],
            kkt_certificates={},
            round_metadata=RoundMetadata(
                num_agents=5, num_committed=5, num_revealed=4,
            ),
        )
        assert result.round_id == "r-001"
        assert result.instruments["ETH-PERP"].clearing_price == Decimal("2500")

    def test_round_config(self):
        from clearing.types import RoundConfig
        rc = RoundConfig(
            round_id="r-001",
            instruments=["ETH-PERP", "SOL-PERP"],
            submission_deadline_ms=5000,
        )
        assert len(rc.instruments) == 2
        assert rc.reveal_window_ms == 5000

    def test_sealed_bundle(self):
        from clearing.types import SealedBundle
        sb = SealedBundle(
            agent_id="a1",
            commitment_hash="abc123",
            ciphertext=b"\x01\x02\x03",
        )
        assert sb.revealed is False
        assert sb.ciphertext == b"\x01\x02\x03"


# ---------------------------------------------------------------------------
# ECIES seal/unseal
# ---------------------------------------------------------------------------

class TestECIES:
    def test_seal_unseal_roundtrip(self):
        from clearing.types import Order
        from clearing.ecies import seal_bundle, unseal_bundle, commitment_hash
        from common.crypto import generate_secp256k1_keypair

        kp = generate_secp256k1_keypair()

        # Need the public key for ECIES — derive from private key
        import ecies
        pubkey_hex = ecies.utils.generate_key().public_key.format(True).hex()

        # Use a fresh keypair from eciespy for the test
        sk = ecies.utils.generate_key()
        sk_hex = sk.secret.hex()
        pk_hex = sk.public_key.format(False).hex()  # uncompressed

        orders = [
            Order(agent_id="a1", instrument="ETH-PERP", side="buy",
                  price=Decimal("2500"), quantity=Decimal("1")),
        ]

        ct = seal_bundle(orders, pk_hex, "round-1", "a1", "deadbeef" * 4)
        assert isinstance(ct, bytes)
        assert len(ct) > 0

        # Unseal
        bundle = unseal_bundle(ct, sk_hex)
        assert bundle["round_id"] == "round-1"
        assert bundle["agent_id"] == "a1"
        assert len(bundle["orders"]) == 1
        assert bundle["orders"][0]["instrument"] == "ETH-PERP"

    def test_commitment_hash_deterministic(self):
        from clearing.ecies import commitment_hash
        ct = b"some deterministic ciphertext bytes"
        h1 = commitment_hash(ct)
        h2 = commitment_hash(ct)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_commitment_hash_different_for_different_input(self):
        from clearing.ecies import commitment_hash
        h1 = commitment_hash(b"data1")
        h2 = commitment_hash(b"data2")
        assert h1 != h2


# ---------------------------------------------------------------------------
# Crypto utilities
# ---------------------------------------------------------------------------

class TestCrypto:
    def test_keypair_generation(self):
        from common.crypto import generate_secp256k1_keypair
        kp = generate_secp256k1_keypair()
        assert len(kp.private_key_hex) == 66 or len(kp.private_key_hex) == 64  # with or without 0x
        assert kp.address.startswith("0x")
        assert len(kp.address) == 42

    def test_keypair_deterministic_with_entropy(self):
        from common.crypto import generate_secp256k1_keypair
        entropy = b"\x01" * 32
        kp1 = generate_secp256k1_keypair(entropy)
        kp2 = generate_secp256k1_keypair(entropy)
        assert kp1.private_key_hex == kp2.private_key_hex
        assert kp1.address == kp2.address

    def test_sha256_hex(self):
        from common.crypto import sha256_hex
        h = sha256_hex(b"hello")
        assert len(h) == 64
        assert h == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    def test_canonical_json_bytes(self):
        from common.crypto import canonical_json_bytes
        data = {"b": 2, "a": 1}
        result = canonical_json_bytes(data)
        assert result == b'{"a":1,"b":2}'

    def test_sign_and_verify(self):
        from common.crypto import generate_secp256k1_keypair, sha256_hex, sign_hash_hex, verify_signature
        kp = generate_secp256k1_keypair()
        msg_hash = sha256_hex(b"test message")
        sig = sign_hash_hex(msg_hash, kp.private_key_hex.replace("0x", ""))
        assert verify_signature(msg_hash, sig, kp.address)

    def test_verify_wrong_key_fails(self):
        from common.crypto import generate_secp256k1_keypair, sha256_hex, sign_hash_hex, verify_signature
        kp1 = generate_secp256k1_keypair()
        kp2 = generate_secp256k1_keypair()
        msg_hash = sha256_hex(b"test")
        sig = sign_hash_hex(msg_hash, kp1.private_key_hex.replace("0x", ""))
        assert not verify_signature(msg_hash, sig, kp2.address)


# ---------------------------------------------------------------------------
# Strategy adapter
# ---------------------------------------------------------------------------

class TestStrategyAdapter:
    def test_decisions_to_orders(self):
        from clearing.types import Order
        from common.models import StrategyDecision
        from agent.strategy_adapter import decisions_to_orders

        decisions = [
            StrategyDecision(action="place_order", instrument="ETH-PERP",
                             side="buy", size=1.0, limit_price=2500.0),
            StrategyDecision(action="noop"),
            StrategyDecision(action="place_order", instrument="SOL-PERP",
                             side="sell", size=0.5, limit_price=150.0),
        ]
        orders = decisions_to_orders(decisions, "agent-1")
        assert len(orders) == 2
        assert orders[0].agent_id == "agent-1"
        assert orders[0].instrument == "ETH-PERP"
        assert orders[0].price == Decimal("2500.00")
        assert orders[1].instrument == "SOL-PERP"

    def test_skips_invalid_decisions(self):
        from common.models import StrategyDecision
        from agent.strategy_adapter import decisions_to_orders

        decisions = [
            StrategyDecision(action="place_order", instrument="X", side="buy",
                             size=0, limit_price=100.0),  # zero size
            StrategyDecision(action="place_order", instrument="X", side="buy",
                             size=1.0, limit_price=0),    # zero price
            StrategyDecision(action="place_order", instrument="X", side="buy",
                             size=-1.0, limit_price=100.0),  # negative size
        ]
        orders = decisions_to_orders(decisions, "a1")
        assert len(orders) == 0

    def test_price_decimal_precision(self):
        from common.models import StrategyDecision
        from agent.strategy_adapter import decisions_to_orders

        decisions = [
            StrategyDecision(action="place_order", instrument="FR-PERP",
                             side="buy", size=100.0, limit_price=0.00045),
            StrategyDecision(action="place_order", instrument="SOL-PERP",
                             side="buy", size=1.0, limit_price=55.123),
            StrategyDecision(action="place_order", instrument="BTC-PERP",
                             side="buy", size=0.01, limit_price=65432.10),
        ]
        orders = decisions_to_orders(decisions, "a1")
        # < 1.0 → 8 decimals
        assert orders[0].price == Decimal("0.00045")
        # < 100.0 → 4 decimals
        assert orders[1].price == Decimal("55.123")
        # >= 100 → 2 decimals
        assert orders[2].price == Decimal("65432.1")

    def test_run_strategy_tick(self):
        from common.models import MarketSnapshot, StrategyDecision
        from sdk.strategy_sdk.base import BaseStrategy, StrategyContext
        from agent.strategy_adapter import run_strategy_tick

        class DummyStrategy(BaseStrategy):
            def on_tick(self, snapshot, context=None):
                return [StrategyDecision(
                    action="place_order",
                    instrument=snapshot.instrument,
                    side="buy",
                    size=1.0,
                    limit_price=snapshot.mid_price,
                )]

        strat = DummyStrategy(strategy_id="dummy")
        snap = MarketSnapshot(instrument="ETH-PERP", mid_price=2500.0,
                              bid=2499.0, ask=2501.0)
        orders = run_strategy_tick(strat, snap, "agent-test")
        assert len(orders) == 1
        assert orders[0].agent_id == "agent-test"
        assert orders[0].price == Decimal("2500.00")


# ---------------------------------------------------------------------------
# Model Registry
# ---------------------------------------------------------------------------

class TestModelRegistry:
    def test_hash_strategy_source(self):
        from sdk.strategy_sdk.registry import hash_strategy_source
        from sdk.strategy_sdk.base import BaseStrategy

        class TestStrat(BaseStrategy):
            def on_tick(self, snapshot, context=None):
                return []

        h = hash_strategy_source(TestStrat)
        assert len(h) == 64
        # Deterministic
        assert h == hash_strategy_source(TestStrat)

    def test_registry_register_and_get(self):
        from sdk.strategy_sdk.registry import ModelRegistry

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "registry.jsonl")
            reg = ModelRegistry(path=path)
            bundle = reg.register("strategies.simple_mm:SimpleMMStrategy")
            assert bundle.strategy_id == "SimpleMMStrategy"
            assert len(bundle.source_hash) == 64

            # Get
            found = reg.get("SimpleMMStrategy")
            assert found is not None
            assert found.source_hash == bundle.source_hash

    def test_registry_verify(self):
        from sdk.strategy_sdk.registry import ModelRegistry

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "registry.jsonl")
            reg = ModelRegistry(path=path)
            bundle = reg.register("strategies.simple_mm:SimpleMMStrategy")
            assert reg.verify(bundle) is True

    def test_registry_list_all(self):
        from sdk.strategy_sdk.registry import ModelRegistry

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "registry.jsonl")
            reg = ModelRegistry(path=path)
            reg.register("strategies.simple_mm:SimpleMMStrategy")
            reg.register("strategies.avellaneda_mm:AvellanedaStoikovMM")
            all_bundles = reg.list_all()
            assert len(all_bundles) == 2
            ids = {b.strategy_id for b in all_bundles}
            assert "SimpleMMStrategy" in ids
            assert "AvellanedaStoikovMM" in ids

    def test_registry_get_nonexistent(self):
        from sdk.strategy_sdk.registry import ModelRegistry

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "registry.jsonl")
            reg = ModelRegistry(path=path)
            assert reg.get("NonExistent") is None


# ---------------------------------------------------------------------------
# AgentClient init
# ---------------------------------------------------------------------------

class TestAgentClientInit:
    def test_client_creation(self):
        from agent.client import AgentClient
        from sdk.strategy_sdk.base import BaseStrategy, StrategyContext
        from common.models import StrategyDecision

        class DummyStrat(BaseStrategy):
            def on_tick(self, snapshot, context=None):
                return []

        client = AgentClient(
            agent_id="test-agent",
            strategy=DummyStrat(),
            relay_url="http://localhost:9999",
        )
        assert client.agent_id == "test-agent"
        assert client.relay_url == "http://localhost:9999"
        assert client.enclave_pubkey is None
        assert len(client._committed_rounds) == 0
