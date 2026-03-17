"""Stock Momentum Breakout (Long-term) — buy breakouts to new highs on volume.

When a stock breaks above a consolidation range on high volume,
it tends to continue trending. Classic Darvas Box / O'Neil CANSLIM approach.
Typical holding: weeks to months.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import sma, atr, ema
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class GapFillStrategy(DaytradeStrategy):
    name = "stock_momentum"
    description = "个股动量突破 — 放量突破新高后持有，追踪止损保护利润"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.lookback: int = p["lookback"]
        self.volume_mult: float = p["volume_mult"]
        self.atr_period: int = p["atr_period"]
        self.trail_atr_mult: float = p["trail_atr_mult"]
        self.trend_ma: int = p["trend_ma"]

        self._trailing_stop: float = 0.0
        self._best_price: float = 0.0

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "lookback": 50,          # period high lookback
            "volume_mult": 1.5,      # breakout volume > avg * mult
            "atr_period": 14,
            "trail_atr_mult": 3.0,   # wide trailing stop
            "trend_ma": 50,          # must be above this MA
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "lookback": (20, 100, 10),
            "volume_mult": (1.0, 3.0, 0.25),
            "trail_atr_mult": (2.0, 5.0, 0.5),
            "trend_ma": (20, 100, 10),
        }

    def reset(self):
        super().reset()
        self._trailing_stop = 0.0
        self._best_price = 0.0

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        min_len = max(self.lookback + 1, self.atr_period + 1, self.trend_ma + 1, 30)
        if len(history) < min_len:
            return None

        if self._in_position:
            atr_vals = atr(history, self.atr_period)
            return self._check_exit(candle, atr_vals[-1])

        closes = [c.close for c in history]
        atr_vals = atr(history, self.atr_period)
        cur_atr = atr_vals[-1]
        if cur_atr != cur_atr:
            return None

        # Trend filter: price above MA
        ma_vals = sma(closes, self.trend_ma)
        if ma_vals[-1] != ma_vals[-1] or candle.close < ma_vals[-1]:
            return None

        # Check for new high (lookback period)
        prev_high = max(c.high for c in history[-self.lookback - 1:-1])

        # Volume check
        avg_vol = sum(c.volume for c in history[-20:]) / 20
        vol_ok = candle.volume >= avg_vol * self.volume_mult if avg_vol > 0 else False

        # Breakout: new high + volume confirmation
        if candle.close > prev_high and vol_ok:
            sl = candle.close - cur_atr * self.trail_atr_mult
            self._in_position = True
            self._position_side = "long"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = 0  # no fixed TP
            self._trailing_stop = sl
            self._best_price = candle.close
            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.LONG, price=candle.close,
                reason=f"放量突破 {self.lookback} 期新高 (vol={candle.volume / avg_vol:.1f}x)",
                confidence=70, stop_loss=sl,
                meta={"prev_high": prev_high, "volume_ratio": round(candle.volume / avg_vol, 1)},
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
