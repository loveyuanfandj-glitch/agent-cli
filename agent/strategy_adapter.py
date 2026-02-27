"""Converts strategy decisions into clearing Order objects."""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from clearing.types import Order
from common.models import MarketSnapshot, StrategyDecision
from sdk.strategy_sdk.base import BaseStrategy, StrategyContext


def decisions_to_orders(
    decisions: List[StrategyDecision],
    agent_id: str,
) -> List[Order]:
    """Convert StrategyDecision list into Order list for batch clearing."""
    orders = []
    for i, d in enumerate(decisions):
        if d.action != "place_order":
            continue
        if d.size <= 0 or d.limit_price <= 0:
            continue
        # Use enough decimal precision for small-scale instruments (e.g. FR-PERP)
        price_decimals = 8 if d.limit_price < 1.0 else 4 if d.limit_price < 100.0 else 2
        orders.append(Order(
            agent_id=agent_id,
            instrument=d.instrument,
            side=d.side,
            price=Decimal(str(round(d.limit_price, price_decimals))),
            quantity=Decimal(str(round(d.size, 6))),
            order_idx=i,
        ))
    return orders


def run_strategy_tick(
    strategy: BaseStrategy,
    snapshot: MarketSnapshot,
    agent_id: str,
    context: Optional[StrategyContext] = None,
) -> List[Order]:
    """Run one strategy tick and return Orders."""
    decisions = strategy.on_tick(snapshot, context=context)
    return decisions_to_orders(decisions, agent_id)
