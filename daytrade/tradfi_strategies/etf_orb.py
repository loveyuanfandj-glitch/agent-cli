"""ETF Opening Range Breakout — trade breakout of first 30min range.

The first 30 minutes of US market open (09:30-10:00 ET) defines a range.
Breakouts from this range with volume tend to continue.
Works best on liquid ETFs like SPY, QQQ, IWM.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import atr, ema
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class ETFOpeningRangeStrategy(DaytradeStrategy):
    name = "etf_orb"
    description = "ETF 开盘区间突破 — 前 30 分钟定区间后突破跟随"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.range_minutes: int = p["range_minutes"]
        self.atr_period: int = p["atr_period"]
        self.atr_sl_mult: float = p["atr_sl_mult"]
        self.risk_reward: float = p["risk_reward"]
        self.volume_confirm: bool = p["volume_confirm"]
        self.volume_mult: float = p["volume_mult"]
        self.use_ema_filter: bool = p["use_ema_filter"]

        self._current_day: int = -1
        self._range_high: float = 0.0
        self._range_low: float = float("inf")
        self._range_set: bool = False
        self._day_candle_count: int = 0
        self._range_candle_target: int = 2  # computed from interval
        self._traded_today: bool = False
        self._avg_volume: float = 0.0

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "range_minutes": 30,
            "atr_period": 14, "atr_sl_mult": 1.0,
            "risk_reward": 2.0,
            "volume_confirm": True, "volume_mult": 1.3,
            "use_ema_filter": True,
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "range_minutes": (15, 60, 15),
            "atr_sl_mult": (0.5, 2.0, 0.25),
            "risk_reward": (1.5, 4.0, 0.5),
            "volume_mult": (1.0, 2.5, 0.25),
        }

    def reset(self):
        super().reset()
        self._current_day = -1
        self._range_high = 0.0
        self._range_low = float("inf")
        self._range_set = False
        self._day_candle_count = 0
        self._traded_today = False
        self._avg_volume = 0.0

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        day = candle.timestamp_ms // 86_400_000

        if day != self._current_day:
            self._current_day = day
            self._range_high = 0.0
            self._range_low = float("inf")
            self._range_set = False
            self._day_candle_count = 0
            self._traded_today = False

        self._day_candle_count += 1

        # Compute how many candles make up the opening range
        if len(history) >= 2:
            interval_ms = history[-1].timestamp_ms - history[-2].timestamp_ms
            interval_min = max(interval_ms // 60_000, 1)
            self._range_candle_target = max(self.range_minutes // interval_min, 1)

        # Build opening range
        if not self._range_set:
            self._range_high = max(self._range_high, candle.high)
            self._range_low = min(self._range_low, candle.low)
            if self._day_candle_count >= self._range_candle_target:
                self._range_set = True
            return None

        if self._in_position:
            return self._check_exit(candle)

        if self._traded_today:
            return None

        if len(history) < self.atr_period + 1:
            return None

        atr_vals = atr(history, self.atr_period)
        cur_atr = atr_vals[-1]
        if cur_atr != cur_atr:
            return None

        # Average volume
        if len(history) >= 20:
            self._avg_volume = sum(c.volume for c in history[-20:]) / 20

        # Volume filter
        if self.volume_confirm and self._avg_volume > 0:
            if candle.volume < self._avg_volume * self.volume_mult:
                return None

        # EMA trend filter
        if self.use_ema_filter and len(history) >= 52:
            closes = [c.close for c in history]
            from daytrade.indicators import ema as ema_fn
            ema50 = ema_fn(closes, 50)
            if candle.close > self._range_high and candle.close < ema50[-1]:
                return None  # skip long below EMA
            if candle.close < self._range_low and candle.close > ema50[-1]:
                return None  # skip short above EMA

        # Breakout above
        if candle.close > self._range_high:
            sl = self._range_low  # SL at range bottom
            risk = candle.close - sl
            tp = candle.close + risk * self.risk_reward
            self._in_position = True
            self._position_side = "long"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = tp
            self._traded_today = True
            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.LONG, price=candle.close,
                reason=f"ETF 开盘突破做多 (>{self._range_high:.2f})",
                confidence=70, stop_loss=sl, take_profit=tp,
                meta={"range_high": self._range_high, "range_low": self._range_low},
            )

        # Breakout below
        if candle.close < self._range_low:
            sl = self._range_high
            risk = sl - candle.close
            tp = candle.close - risk * self.risk_reward
            self._in_position = True
            self._position_side = "short"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = tp
            self._traded_today = True
            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.SHORT, price=candle.close,
                reason=f"ETF 开盘跌破做空 (<{self._range_low:.2f})",
                confidence=70, stop_loss=sl, take_profit=tp,
                meta={"range_high": self._range_high, "range_low": self._range_low},
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
                              price=self._take_profit, reason="止盈")
        else:
            if candle.high >= self._stop_loss:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                              price=self._stop_loss, reason="止损")
            if candle.low <= self._take_profit:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                              price=self._take_profit, reason="止盈")
        return None
