"""ETF Dual Momentum (Long-term) — absolute + relative momentum rotation.

Classic Gary Antonacci dual momentum:
1. Absolute momentum: only buy when asset > its own MA (uptrend)
2. Relative momentum: prefer the stronger one when both are up
Uses monthly/weekly rebalancing. Low frequency, 2-4 trades per year.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import sma, rsi, atr
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class ETFOpeningRangeStrategy(DaytradeStrategy):
    name = "etf_dual_momentum"
    description = "ETF 双动量 — 绝对动量 + 相对强弱轮动"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.momentum_period: int = p["momentum_period"]
        self.trend_ma: int = p["trend_ma"]
        self.atr_period: int = p["atr_period"]
        self.trail_atr_mult: float = p["trail_atr_mult"]
        self.min_momentum_pct: float = p["min_momentum_pct"]

        self._trailing_stop: float = 0.0
        self._best_price: float = 0.0

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "momentum_period": 60,    # ~3 months on daily
            "trend_ma": 200,          # long-term trend (200 day)
            "atr_period": 14,
            "trail_atr_mult": 3.0,
            "min_momentum_pct": 2.0,  # minimum momentum % to enter
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "momentum_period": (20, 120, 20),
            "trend_ma": (100, 250, 50),
            "trail_atr_mult": (2.0, 5.0, 0.5),
            "min_momentum_pct": (0, 5.0, 1.0),
        }

    def reset(self):
        super().reset()
        self._trailing_stop = 0.0
        self._best_price = 0.0

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        min_len = max(self.momentum_period + 1, self.trend_ma + 1, self.atr_period + 1)
        if len(history) < min_len:
            return None

        if self._in_position:
            atr_vals = atr(history, self.atr_period)
            return self._check_exit(candle, atr_vals[-1])

        closes = [c.close for c in history]
        trend = sma(closes, self.trend_ma)
        atr_vals = atr(history, self.atr_period)
        cur_atr = atr_vals[-1]

        if trend[-1] != trend[-1] or cur_atr != cur_atr:
            return None

        # Absolute momentum: price above 200 SMA
        if candle.close < trend[-1]:
            return None

        # Momentum: % gain over lookback period
        past_price = closes[-self.momentum_period - 1]
        if past_price <= 0:
            return None
        momentum = (candle.close - past_price) / past_price * 100

        if momentum < self.min_momentum_pct:
            return None

        # Check if momentum just turned positive (entry signal)
        prev_past = closes[-self.momentum_period - 2] if len(closes) > self.momentum_period + 1 else past_price
        prev_momentum = (closes[-2] - prev_past) / prev_past * 100 if prev_past > 0 else 0

        if momentum >= self.min_momentum_pct and prev_momentum < self.min_momentum_pct:
            sl = candle.close - cur_atr * self.trail_atr_mult
            self._in_position = True
            self._position_side = "long"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = 0
            self._trailing_stop = sl
            self._best_price = candle.close
            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.LONG, price=candle.close,
                reason=f"双动量做多 ({self.momentum_period}期动量={momentum:.1f}%, >MA{self.trend_ma})",
                confidence=75, stop_loss=sl,
                meta={"momentum": round(momentum, 2), "trend_ma": trend[-1]},
            )

        return None

    def _check_exit(self, candle: Candle, cur_atr: float) -> Optional[Signal]:
        if cur_atr != cur_atr:
            return None
        if candle.high > self._best_price:
            self._best_price = candle.high
            self._trailing_stop = max(self._trailing_stop, self._best_price - cur_atr * self.trail_atr_mult)
        if candle.low <= self._trailing_stop:
            self._in_position = False
            return Signal(timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                          price=max(self._trailing_stop, candle.low), reason="追踪止损出场")
        return None
