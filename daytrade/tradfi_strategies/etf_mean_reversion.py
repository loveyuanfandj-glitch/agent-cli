"""ETF Mean Reversion — intraday reversion on liquid index ETFs.

SPY/QQQ tend to revert to VWAP and moving averages during the session.
Uses RSI extremes + Bollinger Band touch as entry trigger.
Target = VWAP or BB midline, whichever is closer.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import rsi, bollinger_bands, vwap, atr
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class ETFMeanReversionStrategy(DaytradeStrategy):
    name = "etf_mean_reversion"
    description = "ETF 日内回归 — RSI+BB 超买超卖反向交易"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.rsi_period: int = p["rsi_period"]
        self.rsi_ob: float = p["rsi_ob"]
        self.rsi_os: float = p["rsi_os"]
        self.bb_period: int = p["bb_period"]
        self.bb_std: float = p["bb_std"]
        self.atr_period: int = p["atr_period"]
        self.atr_sl_mult: float = p["atr_sl_mult"]
        self.max_trades_per_day: int = p["max_trades_per_day"]

        self._current_day: int = -1
        self._trades_today: int = 0

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "rsi_period": 14, "rsi_ob": 75.0, "rsi_os": 25.0,
            "bb_period": 20, "bb_std": 2.0,
            "atr_period": 14, "atr_sl_mult": 1.5,
            "max_trades_per_day": 3,
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "rsi_ob": (65, 85, 5), "rsi_os": (15, 35, 5),
            "bb_std": (1.5, 3.0, 0.25), "atr_sl_mult": (1.0, 2.5, 0.25),
            "max_trades_per_day": (1, 5, 1),
        }

    def reset(self):
        super().reset()
        self._current_day = -1
        self._trades_today = 0

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        min_len = max(self.bb_period + 1, self.rsi_period + 2, self.atr_period + 1)
        if len(history) < min_len:
            return None

        day = candle.timestamp_ms // 86_400_000
        if day != self._current_day:
            self._current_day = day
            self._trades_today = 0

        if self._in_position:
            return self._check_exit(candle, history)

        if self._trades_today >= self.max_trades_per_day:
            return None

        closes = [c.close for c in history]
        rsi_vals = rsi(closes, self.rsi_period)
        upper, mid, lower = bollinger_bands(closes, self.bb_period, self.bb_std)
        atr_vals = atr(history, self.atr_period)
        vwap_vals = vwap(history)

        cur_rsi = rsi_vals[-1]
        prev_rsi = rsi_vals[-2]
        cur_atr = atr_vals[-1]
        cur_vwap = vwap_vals[-1]

        if cur_rsi != cur_rsi or cur_atr != cur_atr:
            return None

        # Long: RSI oversold + at/below lower BB
        if cur_rsi < self.rsi_os and candle.close <= lower[-1] and cur_rsi > prev_rsi:
            sl = candle.close - cur_atr * self.atr_sl_mult
            # Target = closer of VWAP and BB mid
            tp = min(cur_vwap, mid[-1]) if cur_vwap > candle.close else mid[-1]
            self._in_position = True
            self._position_side = "long"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = tp
            self._trades_today += 1
            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.LONG, price=candle.close,
                reason=f"ETF 回归做多 (RSI={cur_rsi:.0f}, BB下轨)",
                confidence=70, stop_loss=sl, take_profit=tp,
                meta={"rsi": cur_rsi, "bb_lower": lower[-1], "vwap": cur_vwap},
            )

        # Short: RSI overbought + at/above upper BB
        if cur_rsi > self.rsi_ob and candle.close >= upper[-1] and cur_rsi < prev_rsi:
            sl = candle.close + cur_atr * self.atr_sl_mult
            tp = max(cur_vwap, mid[-1]) if cur_vwap < candle.close else mid[-1]
            self._in_position = True
            self._position_side = "short"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = tp
            self._trades_today += 1
            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.SHORT, price=candle.close,
                reason=f"ETF 回归做空 (RSI={cur_rsi:.0f}, BB上轨)",
                confidence=70, stop_loss=sl, take_profit=tp,
                meta={"rsi": cur_rsi, "bb_upper": upper[-1], "vwap": cur_vwap},
            )

        return None

    def _check_exit(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
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
                              price=min(candle.close, self._take_profit), reason="止盈 (回归)")
        else:
            if candle.high >= self._stop_loss:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                              price=self._stop_loss, reason="止损")
            if candle.low <= self._take_profit or (cur_vwap > 0 and candle.close <= cur_vwap):
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                              price=max(candle.close, self._take_profit), reason="止盈 (回归)")
        return None
