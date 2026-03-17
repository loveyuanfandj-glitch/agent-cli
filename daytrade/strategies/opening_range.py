"""Opening Range Breakout — trade breakout of the first N candles' range.

Classic intraday strategy: define a range from the first N candles of each
session, then trade breakouts with ATR-based stops.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import atr
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class OpeningRangeBreakout(DaytradeStrategy):
    name = "opening_range"
    description = "开盘区间突破 — 突破首 N 根 K 线区间后顺势入场"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.range_candles: int = p["range_candles"]
        self.atr_period: int = p["atr_period"]
        self.atr_sl_mult: float = p["atr_sl_mult"]
        self.risk_reward: float = p["risk_reward"]
        self.volume_confirm: bool = p["volume_confirm"]
        self.volume_mult: float = p["volume_mult"]

        # Session tracking
        self._session_day: int = -1
        self._range_high: float = 0.0
        self._range_low: float = float("inf")
        self._range_set: bool = False
        self._session_candle_count: int = 0
        self._avg_volume: float = 0.0

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "range_candles": 6,    # first N candles define the range
            "atr_period": 14,
            "atr_sl_mult": 1.0,
            "risk_reward": 2.0,    # TP = risk_reward * SL distance
            "volume_confirm": True,
            "volume_mult": 1.5,    # breakout candle volume > avg * mult
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "range_candles": (3, 12, 1),
            "atr_sl_mult": (0.5, 2.0, 0.25),
            "risk_reward": (1.5, 4.0, 0.5),
            "volume_mult": (1.0, 3.0, 0.25),
        }

    def reset(self):
        super().reset()
        self._session_day = -1
        self._range_high = 0.0
        self._range_low = float("inf")
        self._range_set = False
        self._session_candle_count = 0
        self._avg_volume = 0.0

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        day = candle.timestamp_ms // 86_400_000

        # New session
        if day != self._session_day:
            self._session_day = day
            self._range_high = 0.0
            self._range_low = float("inf")
            self._range_set = False
            self._session_candle_count = 0

        self._session_candle_count += 1

        # Build range
        if not self._range_set:
            self._range_high = max(self._range_high, candle.high)
            self._range_low = min(self._range_low, candle.low)
            if self._session_candle_count >= self.range_candles:
                self._range_set = True
            return None

        # Compute average volume
        if len(history) >= 20:
            recent_vols = [c.volume for c in history[-20:]]
            self._avg_volume = sum(recent_vols) / len(recent_vols)

        # Check exit
        if self._in_position:
            return self._check_exit(candle)

        # Only trade once per session after breakout
        if len(history) < self.atr_period + 1:
            return None

        atr_values = atr(history, self.atr_period)
        cur_atr = atr_values[-1]
        if cur_atr != cur_atr:  # NaN
            return None

        # Volume filter
        if self.volume_confirm and self._avg_volume > 0:
            if candle.volume < self._avg_volume * self.volume_mult:
                return None

        # Breakout above range
        if candle.close > self._range_high:
            sl = candle.close - cur_atr * self.atr_sl_mult
            tp = candle.close + (candle.close - sl) * self.risk_reward
            self._in_position = True
            self._position_side = "long"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = tp
            return Signal(
                timestamp_ms=candle.timestamp_ms,
                side=Side.LONG,
                price=candle.close,
                reason=f"开盘区间突破 (>{self._range_high:.2f})",
                confidence=70,
                stop_loss=sl,
                take_profit=tp,
                meta={"range_high": self._range_high, "range_low": self._range_low},
            )

        # Breakout below range
        if candle.close < self._range_low:
            sl = candle.close + cur_atr * self.atr_sl_mult
            tp = candle.close - (sl - candle.close) * self.risk_reward
            self._in_position = True
            self._position_side = "short"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = tp
            return Signal(
                timestamp_ms=candle.timestamp_ms,
                side=Side.SHORT,
                price=candle.close,
                reason=f"开盘区间跌破 (<{self._range_low:.2f})",
                confidence=70,
                stop_loss=sl,
                take_profit=tp,
                meta={"range_high": self._range_high, "range_low": self._range_low},
            )

        return None

    def _check_exit(self, candle: Candle) -> Optional[Signal]:
        if self._position_side == "long":
            if candle.low <= self._stop_loss:
                self._in_position = False
                return Signal(
                    timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                    price=self._stop_loss, reason="止损",
                )
            if candle.high >= self._take_profit:
                self._in_position = False
                return Signal(
                    timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                    price=self._take_profit, reason="止盈",
                )
        else:
            if candle.high >= self._stop_loss:
                self._in_position = False
                return Signal(
                    timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                    price=self._stop_loss, reason="止损",
                )
            if candle.low <= self._take_profit:
                self._in_position = False
                return Signal(
                    timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                    price=self._take_profit, reason="止盈",
                )
        return None
