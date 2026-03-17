"""Stock MA Pullback Buy (Long-term) — buy pullbacks to moving average in uptrend.

In a confirmed uptrend, buying pullbacks to the 20/50 SMA is one of the
highest-probability setups. Wait for RSI to reach oversold, then enter.
Typical holding: days to weeks.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import sma, ema, rsi, atr
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class VWAPScalpStrategy(DaytradeStrategy):
    name = "stock_ma_pullback"
    description = "个股均线回踩 — 上升趋势中回踩均线买入"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.fast_ma: int = p["fast_ma"]
        self.trend_ma: int = p["trend_ma"]
        self.rsi_period: int = p["rsi_period"]
        self.rsi_threshold: float = p["rsi_threshold"]
        self.atr_period: int = p["atr_period"]
        self.atr_sl_mult: float = p["atr_sl_mult"]
        self.target_pct: float = p["target_pct"]
        self.touch_tolerance_pct: float = p["touch_tolerance_pct"]

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "fast_ma": 20,
            "trend_ma": 50,
            "rsi_period": 14,
            "rsi_threshold": 40.0,
            "atr_period": 14,
            "atr_sl_mult": 2.5,
            "target_pct": 8.0,         # target % gain
            "touch_tolerance_pct": 1.0, # within 1% of MA = "touching"
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "fast_ma": (10, 30, 5),
            "trend_ma": (30, 100, 10),
            "rsi_threshold": (30, 45, 5),
            "atr_sl_mult": (2.0, 4.0, 0.5),
            "target_pct": (5.0, 15.0, 2.5),
            "touch_tolerance_pct": (0.5, 2.0, 0.25),
        }

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        min_len = max(self.trend_ma + 2, self.rsi_period + 2, self.atr_period + 1)
        if len(history) < min_len:
            return None

        if self._in_position:
            return self._check_exit(candle)

        closes = [c.close for c in history]
        fast = sma(closes, self.fast_ma)
        trend = sma(closes, self.trend_ma)
        rsi_vals = rsi(closes, self.rsi_period)
        atr_vals = atr(history, self.atr_period)

        cur_fast = fast[-1]
        cur_trend = trend[-1]
        cur_rsi = rsi_vals[-1]
        cur_atr = atr_vals[-1]

        if any(v != v for v in [cur_fast, cur_trend, cur_rsi, cur_atr]):
            return None

        # Uptrend: fast MA > slow MA, price above slow MA
        if cur_fast <= cur_trend:
            return None

        # Pullback: price near fast MA
        dist = abs(candle.close - cur_fast) / cur_fast * 100
        if dist > self.touch_tolerance_pct:
            return None

        # RSI confirmation
        if cur_rsi > self.rsi_threshold:
            return None

        # Enter long
        sl = candle.close - cur_atr * self.atr_sl_mult
        tp = candle.close * (1 + self.target_pct / 100)
        self._in_position = True
        self._position_side = "long"
        self._entry_price = candle.close
        self._entry_time = candle.timestamp_ms
        self._stop_loss = sl
        self._take_profit = tp
        return Signal(
            timestamp_ms=candle.timestamp_ms, side=Side.LONG, price=candle.close,
            reason=f"均线回踩做多 (MA{self.fast_ma}={cur_fast:.2f}, RSI={cur_rsi:.0f})",
            confidence=70, stop_loss=sl, take_profit=tp,
            meta={"fast_ma": cur_fast, "trend_ma": cur_trend, "rsi": cur_rsi, "dist_pct": dist},
        )

    def _check_exit(self, candle: Candle) -> Optional[Signal]:
        if candle.low <= self._stop_loss:
            self._in_position = False
            return Signal(timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                          price=self._stop_loss, reason="止损")
        if candle.high >= self._take_profit:
            self._in_position = False
            return Signal(timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                          price=self._take_profit, reason=f"止盈 (+{self.target_pct}%)")
        return None
