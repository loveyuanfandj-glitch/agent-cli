"""HK Overnight Follow — trade HK open based on US overnight move.

Hong Kong market opens at 09:30 HKT, after US market closes.
When US tech (NASDAQ) has a strong move overnight, HK tech stocks
gap in the same direction but typically only follow 50-70%.
This creates a predictable opening pattern.

Logic:
1. Check US close (QQQ or NASDAQ) vs previous close
2. If US moved > threshold → expect HK to gap and follow
3. Enter at HK open, target 50-70% of US move, tight stop
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import atr, ema
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class HKOvernightFollowStrategy(DaytradeStrategy):
    name = "hk_overnight_follow"
    description = "美股隔夜跟随 — 美股大涨/大跌后港股开盘跟随入场"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.us_threshold_pct: float = p["us_threshold_pct"]
        self.follow_ratio: float = p["follow_ratio"]
        self.atr_period: int = p["atr_period"]
        self.atr_sl_mult: float = p["atr_sl_mult"]
        self.gap_min_pct: float = p["gap_min_pct"]
        self.max_gap_pct: float = p["max_gap_pct"]

        self._current_day: int = -1
        self._prev_close: float = 0.0
        self._traded_today: bool = False

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "us_threshold_pct": 0.8,   # HK gap must be > this % to trigger
            "follow_ratio": 0.6,       # target = 60% of gap filled/extended
            "atr_period": 14,
            "atr_sl_mult": 1.5,
            "gap_min_pct": 0.5,        # minimum gap to trade
            "max_gap_pct": 5.0,        # skip extreme gaps (black swan)
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "us_threshold_pct": (0.3, 2.0, 0.1),
            "follow_ratio": (0.3, 0.8, 0.1),
            "atr_sl_mult": (1.0, 3.0, 0.25),
            "gap_min_pct": (0.3, 1.5, 0.1),
            "max_gap_pct": (3.0, 8.0, 1.0),
        }

    def reset(self):
        super().reset()
        self._current_day = -1
        self._prev_close = 0.0
        self._traded_today = False

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        day = candle.timestamp_ms // 86_400_000

        # New day
        if day != self._current_day:
            # Save previous day's last close
            if self._current_day != -1 and len(history) >= 2:
                for c in reversed(history[:-1]):
                    if c.timestamp_ms // 86_400_000 != day:
                        self._prev_close = c.close
                        break
            self._current_day = day
            self._traded_today = False

        if self._in_position:
            return self._check_exit(candle)

        if self._traded_today or self._prev_close <= 0:
            return None

        if len(history) < self.atr_period + 1:
            return None

        # Only trade on first candle of the day (opening)
        day_candles = [c for c in history if c.timestamp_ms // 86_400_000 == day]
        if len(day_candles) > 2:
            return None  # only first 1-2 candles

        # Measure gap
        gap_pct = (candle.open - self._prev_close) / self._prev_close * 100

        if abs(gap_pct) < self.gap_min_pct or abs(gap_pct) > self.max_gap_pct:
            return None

        atr_vals = atr(history, self.atr_period)
        cur_atr = atr_vals[-1]
        if cur_atr != cur_atr:
            return None

        # Gap up → follow long (US was up overnight, HK follows)
        if gap_pct >= self.us_threshold_pct:
            # Expect HK to continue in gap direction
            gap_size = candle.open - self._prev_close
            tp = candle.close + gap_size * self.follow_ratio
            sl = candle.close - cur_atr * self.atr_sl_mult

            self._in_position = True
            self._position_side = "long"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = tp
            self._traded_today = True

            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.LONG, price=candle.close,
                reason=f"美股隔夜跟随做多 (跳空+{gap_pct:.1f}%)",
                confidence=min(60 + abs(gap_pct) * 10, 90),
                stop_loss=sl, take_profit=tp,
                meta={"gap_pct": round(gap_pct, 2), "prev_close": self._prev_close},
            )

        # Gap down → follow short
        if gap_pct <= -self.us_threshold_pct:
            gap_size = self._prev_close - candle.open
            tp = candle.close - gap_size * self.follow_ratio
            sl = candle.close + cur_atr * self.atr_sl_mult

            self._in_position = True
            self._position_side = "short"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = tp
            self._traded_today = True

            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.SHORT, price=candle.close,
                reason=f"美股隔夜跟随做空 (跳空{gap_pct:.1f}%)",
                confidence=min(60 + abs(gap_pct) * 10, 90),
                stop_loss=sl, take_profit=tp,
                meta={"gap_pct": round(gap_pct, 2), "prev_close": self._prev_close},
            )

        return None

    def _check_exit(self, candle: Candle) -> Optional[Signal]:
        if self._position_side == "long":
            if candle.low <= self._stop_loss:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                              price=self._stop_loss, reason="止损")
            if candle.high >= self._take_profit:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                              price=self._take_profit, reason="止盈 (跟随目标)")
        else:
            if candle.high >= self._stop_loss:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                              price=self._stop_loss, reason="止损")
            if candle.low <= self._take_profit:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                              price=self._take_profit, reason="止盈 (跟随目标)")
        return None
