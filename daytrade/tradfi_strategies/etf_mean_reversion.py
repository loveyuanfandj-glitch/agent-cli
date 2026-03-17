"""ETF 定投增强 (Long-term) — enhanced DCA with RSI timing.

Improves on simple dollar-cost averaging by timing entries:
- Buy more when RSI is oversold (fear = opportunity)
- Buy less or skip when RSI is overbought
- Never sell, only accumulate (long-only)
Uses weekly/daily timeframe. Exit only via trailing stop on major trend break.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import sma, rsi, atr
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class ETFMeanReversionStrategy(DaytradeStrategy):
    name = "etf_smart_dca"
    description = "ETF 智能定投 — RSI 择时增强的定投策略"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.rsi_period: int = p["rsi_period"]
        self.rsi_buy_threshold: float = p["rsi_buy_threshold"]
        self.trend_ma: int = p["trend_ma"]
        self.atr_period: int = p["atr_period"]
        self.trail_atr_mult: float = p["trail_atr_mult"]
        self.buy_interval: int = p["buy_interval"]

        self._candle_count: int = 0
        self._trailing_stop: float = 0.0
        self._best_price: float = 0.0

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "rsi_period": 14,
            "rsi_buy_threshold": 40.0,  # buy when RSI < this
            "trend_ma": 200,
            "atr_period": 14,
            "trail_atr_mult": 4.0,      # very wide stop for long term
            "buy_interval": 20,         # check every N candles (~monthly on daily)
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "rsi_buy_threshold": (30, 50, 5),
            "trend_ma": (100, 250, 50),
            "trail_atr_mult": (3.0, 6.0, 0.5),
            "buy_interval": (5, 30, 5),
        }

    def reset(self):
        super().reset()
        self._candle_count = 0
        self._trailing_stop = 0.0
        self._best_price = 0.0

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        self._candle_count += 1
        min_len = max(self.trend_ma + 1, self.rsi_period + 2, self.atr_period + 1)
        if len(history) < min_len:
            return None

        if self._in_position:
            atr_vals = atr(history, self.atr_period)
            return self._check_exit(candle, atr_vals[-1])

        # Only evaluate at buy intervals
        if self._candle_count % self.buy_interval != 0:
            return None

        closes = [c.close for c in history]
        trend = sma(closes, self.trend_ma)
        rsi_vals = rsi(closes, self.rsi_period)
        atr_vals = atr(history, self.atr_period)

        cur_trend = trend[-1]
        cur_rsi = rsi_vals[-1]
        cur_atr = atr_vals[-1]

        if any(v != v for v in [cur_trend, cur_rsi, cur_atr]):
            return None

        # Long-term trend must be up or flat (price not too far below MA200)
        max_below_pct = 10.0  # allow buying up to 10% below MA200
        if candle.close < cur_trend * (1 - max_below_pct / 100):
            return None

        # RSI timing: only buy when RSI shows weakness (good value)
        if cur_rsi > self.rsi_buy_threshold:
            return None

        # Enter
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
            reason=f"智能定投买入 (RSI={cur_rsi:.0f}, 低于阈值{self.rsi_buy_threshold})",
            confidence=65, stop_loss=sl,
            meta={"rsi": round(cur_rsi, 1), "trend_ma": cur_trend,
                  "above_ma": candle.close > cur_trend},
        )

    def _check_exit(self, candle: Candle, cur_atr: float) -> Optional[Signal]:
        if cur_atr != cur_atr:
            return None
        if candle.high > self._best_price:
            self._best_price = candle.high
            self._trailing_stop = max(self._trailing_stop, self._best_price - cur_atr * self.trail_atr_mult)
        if candle.low <= self._trailing_stop:
            self._in_position = False
            return Signal(timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                          price=max(self._trailing_stop, candle.low), reason="趋势破位出场")
        return None
