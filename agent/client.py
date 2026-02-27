"""Agent client — connects to the parent relay and participates in clearing rounds.

Flow per round:
  1. Receive market snapshot (from parent or direct)
  2. Run strategy -> get orders
  3. Seal orders via ECIES to enclave pubkey
  4. Compute commitment = SHA-256(ciphertext)
  5. POST /v1/commit with commitment hash
  6. POST /v1/reveal with sealed bundle
  7. GET /v1/result/{round_id} for clearing result
"""
from __future__ import annotations

import logging
import os
import time
from typing import Dict, List, Optional

import requests

from clearing.ecies import commitment_hash, seal_bundle
from clearing.types import Order
from common.models import MarketSnapshot
from sdk.strategy_sdk.base import BaseStrategy, StrategyContext
from agent.strategy_adapter import run_strategy_tick

log = logging.getLogger("agent_client")


class AgentClient:
    """Agent that connects to the parent relay over HTTP."""

    def __init__(
        self,
        agent_id: str,
        strategy: BaseStrategy,
        relay_url: str = "http://localhost:8080",
    ):
        self.agent_id = agent_id
        self.strategy = strategy
        self.relay_url = relay_url.rstrip("/")
        self.enclave_pubkey: Optional[str] = None
        self._committed_rounds: set = set()

    def fetch_identity(self) -> Dict:
        """GET /v1/identity to get enclave pubkey."""
        resp = requests.get(f"{self.relay_url}/v1/identity", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        self.enclave_pubkey = data["enclave_pubkey"]
        log.info("Enclave pubkey: %s...%s",
                 self.enclave_pubkey[:10], self.enclave_pubkey[-6:])
        return data

    def _build_context(self, snapshot: MarketSnapshot) -> Optional[StrategyContext]:
        """Fetch position from relay and build StrategyContext."""
        pos_data = self.fetch_position()
        if pos_data is None:
            return None
        inst_data = pos_data.get(snapshot.instrument, {})
        net_qty = float(inst_data.get("net_qty", 0))
        notional = float(inst_data.get("notional", 0))
        unrealized = float(inst_data.get("unrealized_pnl", 0))
        realized = float(inst_data.get("realized_pnl", 0))
        return StrategyContext(
            snapshot=snapshot,
            position_qty=net_qty,
            position_notional=notional,
            unrealized_pnl=unrealized,
            realized_pnl=realized,
            reduce_only=pos_data.get("reduce_only", False),
            safe_mode=pos_data.get("safe_mode", False),
            meta={"house_net_qty": float(pos_data.get("house_net_qty", 0))},
        )

    def participate_round(
        self,
        round_id: str,
        snapshot: MarketSnapshot,
    ) -> Optional[Dict]:
        """Run strategy, seal orders, commit, wait for reveal phase, reveal."""
        if self.enclave_pubkey is None:
            self.fetch_identity()

        context = self._build_context(snapshot)

        # Run strategy
        orders = run_strategy_tick(self.strategy, snapshot, self.agent_id, context=context)
        if not orders:
            log.info("[%s] No orders this round", self.agent_id)
            return None

        log.info("[%s] Generated %d orders", self.agent_id, len(orders))

        # Seal
        nonce = os.urandom(16).hex()
        ciphertext = seal_bundle(
            orders, self.enclave_pubkey, round_id, self.agent_id, nonce,
        )
        commit_hash = commitment_hash(ciphertext)

        # Commit
        resp = requests.post(
            f"{self.relay_url}/v1/commit",
            json={"agent_id": self.agent_id, "commitment_hash": commit_hash},
            timeout=5,
        )
        resp.raise_for_status()
        commit_result = resp.json()
        if not commit_result.get("ok"):
            log.warning("[%s] Commit rejected: %s", self.agent_id, commit_result.get("message"))
            return None

        log.info("[%s] Committed for round %s, waiting for reveal phase...", self.agent_id, round_id)

        # Wait for reveal phase
        for _ in range(60):
            time.sleep(0.5)
            try:
                snap_resp = requests.get(f"{self.relay_url}/v1/snapshot", timeout=5)
                snap_resp.raise_for_status()
                info = snap_resp.json()
                phase = info.get("phase", "")
                cur_round = info.get("round_id", "")
                if cur_round != round_id:
                    log.warning("[%s] Round changed during wait", self.agent_id)
                    return None
                if phase == "reveal":
                    break
            except Exception:
                pass
        else:
            log.warning("[%s] Timed out waiting for reveal phase", self.agent_id)
            return None

        # Reveal
        resp = requests.post(
            f"{self.relay_url}/v1/reveal",
            json={
                "agent_id": self.agent_id,
                "ciphertext_hex": ciphertext.hex(),
                "commitment_hash": commit_hash,
            },
            timeout=5,
        )
        resp.raise_for_status()
        reveal_result = resp.json()
        if not reveal_result.get("ok"):
            log.warning("[%s] Reveal rejected: %s", self.agent_id, reveal_result.get("message"))
            return None

        log.info("[%s] Committed and revealed for round %s", self.agent_id, round_id)
        return {"round_id": round_id, "num_orders": len(orders), "commit_hash": commit_hash}

    def fetch_result(self, round_id: str) -> Optional[Dict]:
        """GET /v1/result/{round_id}."""
        try:
            resp = requests.get(f"{self.relay_url}/v1/result/{round_id}", timeout=5)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.warning("[%s] Failed to fetch result: %s", self.agent_id, e)
            return None

    def poll_and_participate(self) -> Optional[Dict]:
        """Poll relay for current round, participate if in commit phase."""
        resp = requests.get(f"{self.relay_url}/v1/snapshot", timeout=5)
        resp.raise_for_status()
        info = resp.json()

        round_id = info.get("round_id")
        phase = info.get("phase")
        snapshot_data = info.get("snapshot")

        if not round_id or phase != "commit" or not snapshot_data:
            return None

        if round_id in self._committed_rounds:
            return None
        self._committed_rounds.add(round_id)

        snapshot = MarketSnapshot(**snapshot_data)
        return self.participate_round(round_id, snapshot)

    def fetch_position(self) -> Optional[Dict]:
        """GET /v1/positions/{agent_id}."""
        try:
            resp = requests.get(
                f"{self.relay_url}/v1/positions/{self.agent_id}", timeout=5,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.warning("[%s] Failed to fetch position: %s", self.agent_id, e)
            return None

    def fetch_scoreboard(self) -> Optional[Dict]:
        """GET /v1/scoreboard."""
        try:
            resp = requests.get(f"{self.relay_url}/v1/scoreboard", timeout=5)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.warning("Failed to fetch scoreboard: %s", e)
            return None
