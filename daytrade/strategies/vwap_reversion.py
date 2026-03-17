"""VWAP Reversion — trade mean reversion to VWAP.

When price deviates significantly from VWAP, enter expecting reversion.
Best for range-bound / choppy markets. Uses ATR-based stops.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import vwap, atr, rsi
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class VWAPReversionStrategy(DaytradeStrategy):
    name = "vwap_reversion"
    description = "VWAP 回归 — 价格偏离 VWAP 时反向交易"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.deviation_pct: float = p["deviation_pct"]
        self.atr_period: int = p["atr_period"]
        self.atr_sl_mult: float = p["atr_sl_mult"]
        self.atr_tp_mult: float = p["atr_tp_mult"]
        self.rsi_filter: bool = p["rsi_filter"]
        self.rsi_period: int = p["rsi_period"]
        self.rsi_ob: float = p["rsi_ob"]
        self.rsi_os: float = p["rsi_os"]

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "deviation_pct": 0.3,   # % deviation from VWAP to trigger
            "atr_period": 14,
            "atr_sl_mult": 1.5,    # ATR multiplier for stop loss
            "atr_tp_mult": 2.0,    # ATR multiplier for take profit
            "rsi_filter": True,    # require RSI confirmation
            "rsi_period": 14,
            "rsi_ob": 70.0,        # overbought threshold
            "rsi_os": 30.0,        # oversold threshold
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "deviation_pct": (0.1, 1.0, 0.05),
            "atr_sl_mult": (1.0, 3.0, 0.25),
            "atr_tp_mult": (1.5, 4.0, 0.25),
            "rsi_ob": (65, 80, 5),
            "rsi_os": (20, 35, 5),
        }

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        if len(history) < max(self.atr_period + 1, 20):
            return None

        vwap_values = vwap(history)
        atr_values = atr(history, self.atr_period)
        cur_vwap = vwap_values[-1]
        cur_atr = atr_values[-1]

        if cur_vwap <= 0 or cur_atr != cur_atr:  # NaN check
            return None

        deviation = (candle.close - cur_vwap) / cur_vwap * 100

        # RSI filter
        closes = [c.close for c in history]
        rsi_values = rsi(closes, self.rsi_period)
        cur_rsi = rsi_values[-1] if rsi_values else 50

        # Check exit first
        if self._in_position:
            return self._check_exit(candle)

        # Entry: price above VWAP + RSI overbought -> short
        if deviation > self.deviation_pct:
            if self.rsi_filter and cur_rsi < self.rsi_ob:
                return None
            sl = candle.close + cur_atr * self.atr_sl_mult
            tp = candle.close - cur_atr * self.atr_tp_mult
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
                reason=f"VWAP 偏离 {deviation:.2f}% (RSI={cur_rsi:.0f})",
                confidence=min(abs(deviation) / self.deviation_pct * 50, 100),
                stop_loss=sl,
                take_profit=tp,
                meta={"deviation": deviation, "vwap": cur_vwap, "rsi": cur_rsi},
            )

        # Entry: price below VWAP + RSI oversold -> long
        if deviation < -self.deviation_pct:
            if self.rsi_filter and cur_rsi > self.rsi_os:
                return None
            sl = candle.close - cur_atr * self.atr_sl_mult
            tp = candle.close + cur_atr * self.atr_tp_mult
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
                reason=f"VWAP 偏离 {deviation:.2f}% (RSI={cur_rsi:.0f})",
                confidence=min(abs(deviation) / self.deviation_pct * 50, 100),
                stop_loss=sl,
                take_profit=tp,
                meta={"deviation": deviation, "vwap": cur_vwap, "rsi": cur_rsi},
            )

        return None

    def _check_exit(self, candle: Candle) -> Optional[Signal]:
        """Check stop loss, take profit, or VWAP touch for exit."""
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
