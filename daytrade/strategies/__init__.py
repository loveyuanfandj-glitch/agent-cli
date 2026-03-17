"""Intraday strategy registry."""
from __future__ import annotations

from typing import Dict, Type

from daytrade.strategies.base import DaytradeStrategy
from daytrade.strategies.vwap_reversion import VWAPReversionStrategy
from daytrade.strategies.opening_range import OpeningRangeBreakout
from daytrade.strategies.session_momentum import SessionMomentumStrategy
from daytrade.strategies.ema_crossover import EMACrossoverStrategy
from daytrade.strategies.rsi_reversal import RSIReversalStrategy
from daytrade.strategies.session_breakout import SessionBreakoutStrategy
from daytrade.strategies.liquidation_bounce import LiquidationBounceStrategy

STRATEGY_REGISTRY: Dict[str, Type[DaytradeStrategy]] = {
    "session_breakout": SessionBreakoutStrategy,
    "liquidation_bounce": LiquidationBounceStrategy,
    "vwap_reversion": VWAPReversionStrategy,
    "opening_range": OpeningRangeBreakout,
    "session_momentum": SessionMomentumStrategy,
    "ema_crossover": EMACrossoverStrategy,
    "rsi_reversal": RSIReversalStrategy,
}

STRATEGY_DESCRIPTIONS: Dict[str, str] = {
    "session_breakout": "时段区间突破 — 亚盘定区间，欧美盘放量突破入场 (推荐)",
    "liquidation_bounce": "清算反弹 — OI 骤降 + 超跌放量后捕捉反弹 (推荐)",
    "vwap_reversion": "VWAP 回归 — 价格偏离 VWAP 时反向交易，适合震荡行情",
    "opening_range": "开盘区间突破 — 突破首 N 根 K 线形成的区间后顺势入场",
    "session_momentum": "Session 动量 — 检测强趋势 + 回调入场，趋势跟随",
    "ema_crossover": "EMA 交叉 — 快慢均线金叉/死叉信号，经典趋势策略",
    "rsi_reversal": "RSI 反转 — RSI 超买超卖 + 价格确认反转入场",
}

__all__ = [
    "STRATEGY_REGISTRY",
    "STRATEGY_DESCRIPTIONS",
    "DaytradeStrategy",
    "SessionBreakoutStrategy",
    "LiquidationBounceStrategy",
    "VWAPReversionStrategy",
    "OpeningRangeBreakout",
    "SessionMomentumStrategy",
    "EMACrossoverStrategy",
    "RSIReversalStrategy",
]
