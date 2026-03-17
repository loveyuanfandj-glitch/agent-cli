"""VWAP Scalp — trade around the institutional benchmark price.

VWAP is the most important intraday benchmark for institutional traders.
Stocks tend to revert to VWAP repeatedly during the session.
Enter when price deviates significantly, exit on touch/cross.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import vwap, atr, rsi
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class VWAPScalpStrategy(DaytradeStrategy):
    name = "stock_vwap_scalp"
    description = "VWAP 刮头皮 — 偏离 VWAP 后反向交易"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.deviation_pct: float = p["deviation_pct"]
        self.atr_period: int = p["atr_period"]
        self.atr_sl_mult: float = p["atr_sl_mult"]
        self.rsi_filter: bool = p["rsi_filter"]
        self.rsi_ob: float = p["rsi_ob"]
        self.rsi_os: float = p["rsi_os"]
        self.max_trades_per_day: int = p["max_trades_per_day"]

        self._current_day: int = -1
        self._trades_today: int = 0

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "deviation_pct": 0.3,
            "atr_period": 14, "atr_sl_mult": 1.2,
            "rsi_filter": True, "rsi_ob": 70.0, "rsi_os": 30.0,
            "max_trades_per_day": 3,
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "deviation_pct": (0.1, 0.8, 0.05),
            "atr_sl_mult": (0.8, 2.0, 0.2),
            "rsi_ob": (65, 80, 5), "rsi_os": (20, 35, 5),
            "max_trades_per_day": (1, 5, 1),
        }

    def reset(self):
        super().reset()
        self._current_day = -1
        self._trades_today = 0

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        if len(history) < max(self.atr_period + 1, 20):
            return None

        day = candle.timestamp_ms // 86_400_000
        if day != self._current_day:
            self._current_day = day
            self._trades_today = 0

        if self._in_position:
            return self._check_exit(candle, history)

        if self._trades_today >= self.max_trades_per_day:
            return None

        vwap_vals = vwap(history)
        cur_vwap = vwap_vals[-1]
        if cur_vwap <= 0:
            return None

        deviation = (candle.close - cur_vwap) / cur_vwap * 100
        atr_vals = atr(history, self.atr_period)
        cur_atr = atr_vals[-1]
        if cur_atr != cur_atr:
            return None

        # RSI filter
        closes = [c.close for c in history]
        rsi_vals = rsi(closes, 14)
        cur_rsi = rsi_vals[-1] if rsi_vals[-1] == rsi_vals[-1] else 50

        # Long: below VWAP + RSI oversold
        if deviation < -self.deviation_pct:
            if self.rsi_filter and cur_rsi > self.rsi_os:
                return None
            sl = candle.close - cur_atr * self.atr_sl_mult
            tp = cur_vwap  # target = VWAP touch
            self._in_position = True
            self._position_side = "long"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = tp
            self._trades_today += 1
            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.LONG, price=candle.close,
                reason=f"VWAP 做多 (偏离{deviation:.2f}%, RSI={cur_rsi:.0f})",
                confidence=65, stop_loss=sl, take_profit=tp,
                meta={"deviation": deviation, "vwap": cur_vwap, "rsi": cur_rsi},
            )

        # Short: above VWAP + RSI overbought
        if deviation > self.deviation_pct:
            if self.rsi_filter and cur_rsi < self.rsi_ob:
                return None
            sl = candle.close + cur_atr * self.atr_sl_mult
            tp = cur_vwap
            self._in_position = True
            self._position_side = "short"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = tp
            self._trades_today += 1
            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.SHORT, price=candle.close,
                reason=f"VWAP 做空 (偏离+{deviation:.2f}%, RSI={cur_rsi:.0f})",
                confidence=65, stop_loss=sl, take_profit=tp,
                meta={"deviation": deviation, "vwap": cur_vwap, "rsi": cur_rsi},
            )

        return None

    def _check_exit(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        # Also exit when price crosses back through VWAP
        vwap_vals = vwap(history)
        cur_vwap = vwap_vals[-1] if vwap_vals else 0

        if self._position_side == "long":
            if candle.low <= self._stop_loss:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                              price=self._stop_loss, reason="止损")
            if candle.high >= self._take_profit or (cur_vwap > 0 and candle.close >= cur_vwap):
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                              price=min(candle.close, self._take_profit), reason="止盈 (触及VWAP)")
        else:
            if candle.high >= self._stop_loss:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                              price=self._stop_loss, reason="止损")
            if candle.low <= self._take_profit or (cur_vwap > 0 and candle.close <= cur_vwap):
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                              price=max(candle.close, self._take_profit), reason="止盈 (触及VWAP)")
        return None
