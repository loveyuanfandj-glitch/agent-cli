"""EMA Crossover — classic fast/slow EMA crossover with trend filter.

Enters on golden/death cross, uses ATR-based stops.
Optional trend filter: only trade in the direction of the higher-timeframe trend.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import ema, atr, rsi
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class EMACrossoverStrategy(DaytradeStrategy):
    name = "ema_crossover"
    description = "EMA 交叉 — 快慢均线金叉/死叉"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.fast_period: int = p["fast_period"]
        self.slow_period: int = p["slow_period"]
        self.trend_period: int = p["trend_period"]
        self.use_trend_filter: bool = p["use_trend_filter"]
        self.atr_period: int = p["atr_period"]
        self.atr_sl_mult: float = p["atr_sl_mult"]
        self.risk_reward: float = p["risk_reward"]

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "fast_period": 8,
            "slow_period": 21,
            "trend_period": 50,     # higher TF trend filter
            "use_trend_filter": True,
            "atr_period": 14,
            "atr_sl_mult": 1.5,
            "risk_reward": 2.0,
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "fast_period": (5, 15, 1),
            "slow_period": (15, 50, 5),
            "trend_period": (30, 100, 10),
            "atr_sl_mult": (1.0, 3.0, 0.25),
            "risk_reward": (1.5, 4.0, 0.5),
        }

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        min_len = max(self.trend_period + 2, self.atr_period + 1)
        if len(history) < min_len:
            return None

        closes = [c.close for c in history]
        fast = ema(closes, self.fast_period)
        slow = ema(closes, self.slow_period)
        trend = ema(closes, self.trend_period)
        atr_values = atr(history, self.atr_period)

        cur_atr = atr_values[-1]
        if cur_atr != cur_atr:
            return None

        # Check exit
        if self._in_position:
            return self._check_exit(candle)

        # Crossover detection
        prev_fast_above = fast[-2] > slow[-2]
        cur_fast_above = fast[-1] > slow[-1]

        # Golden cross: fast crosses above slow
        if cur_fast_above and not prev_fast_above:
            if self.use_trend_filter and closes[-1] < trend[-1]:
                return None  # price below trend — skip bullish signal

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
                reason=f"EMA 金叉 ({self.fast_period}/{self.slow_period})",
                confidence=65,
                stop_loss=sl,
                take_profit=tp,
                meta={"fast_ema": fast[-1], "slow_ema": slow[-1]},
            )

        # Death cross: fast crosses below slow
        if not cur_fast_above and prev_fast_above:
            if self.use_trend_filter and closes[-1] > trend[-1]:
                return None  # price above trend — skip bearish signal

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
                reason=f"EMA 死叉 ({self.fast_period}/{self.slow_period})",
                confidence=65,
                stop_loss=sl,
                take_profit=tp,
                meta={"fast_ema": fast[-1], "slow_ema": slow[-1]},
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
