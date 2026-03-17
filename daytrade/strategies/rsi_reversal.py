"""RSI Reversal — enter on RSI extremes with price confirmation.

Waits for RSI to reach overbought/oversold, then confirms with a
reversal candle (e.g., pin bar, engulfing). Uses Bollinger Band
proximity as secondary filter.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import rsi, bollinger_bands, atr
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class RSIReversalStrategy(DaytradeStrategy):
    name = "rsi_reversal"
    description = "RSI 反转 — RSI 超买超卖 + 反转确认入场"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.rsi_period: int = p["rsi_period"]
        self.rsi_ob: float = p["rsi_ob"]
        self.rsi_os: float = p["rsi_os"]
        self.bb_period: int = p["bb_period"]
        self.bb_std: float = p["bb_std"]
        self.use_bb_filter: bool = p["use_bb_filter"]
        self.atr_period: int = p["atr_period"]
        self.atr_sl_mult: float = p["atr_sl_mult"]
        self.risk_reward: float = p["risk_reward"]
        self.require_reversal_candle: bool = p["require_reversal_candle"]

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "rsi_period": 14,
            "rsi_ob": 75.0,
            "rsi_os": 25.0,
            "bb_period": 20,
            "bb_std": 2.0,
            "use_bb_filter": True,
            "atr_period": 14,
            "atr_sl_mult": 1.5,
            "risk_reward": 2.0,
            "require_reversal_candle": True,
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "rsi_ob": (65, 85, 5),
            "rsi_os": (15, 35, 5),
            "atr_sl_mult": (1.0, 3.0, 0.25),
            "risk_reward": (1.5, 4.0, 0.5),
        }

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        min_len = max(self.rsi_period + 2, self.bb_period + 1, self.atr_period + 1)
        if len(history) < min_len:
            return None

        closes = [c.close for c in history]
        rsi_values = rsi(closes, self.rsi_period)
        atr_values = atr(history, self.atr_period)
        cur_rsi = rsi_values[-1]
        prev_rsi = rsi_values[-2]
        cur_atr = atr_values[-1]

        if cur_rsi != cur_rsi or cur_atr != cur_atr:
            return None

        # Check exit
        if self._in_position:
            return self._check_exit(candle)

        # Bollinger Bands filter
        bb_ok_long = True
        bb_ok_short = True
        if self.use_bb_filter:
            upper, mid, lower = bollinger_bands(closes, self.bb_period, self.bb_std)
            bb_ok_long = candle.close <= lower[-1]  # near lower band
            bb_ok_short = candle.close >= upper[-1]  # near upper band

        # Reversal candle check
        prev_candle = history[-2]
        is_bullish_reversal = self._is_bullish_reversal(candle, prev_candle)
        is_bearish_reversal = self._is_bearish_reversal(candle, prev_candle)

        # Long: RSI was oversold and now turning up + bullish reversal candle
        if prev_rsi < self.rsi_os and cur_rsi > prev_rsi:
            if not self.require_reversal_candle or is_bullish_reversal:
                if not self.use_bb_filter or bb_ok_long:
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
                        reason=f"RSI 超卖反转 ({cur_rsi:.0f})",
                        confidence=70,
                        stop_loss=sl,
                        take_profit=tp,
                        meta={"rsi": cur_rsi, "reversal": is_bullish_reversal},
                    )

        # Short: RSI was overbought and now turning down + bearish reversal candle
        if prev_rsi > self.rsi_ob and cur_rsi < prev_rsi:
            if not self.require_reversal_candle or is_bearish_reversal:
                if not self.use_bb_filter or bb_ok_short:
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
                        reason=f"RSI 超买反转 ({cur_rsi:.0f})",
                        confidence=70,
                        stop_loss=sl,
                        take_profit=tp,
                        meta={"rsi": cur_rsi, "reversal": is_bearish_reversal},
                    )

        return None

    @staticmethod
    def _is_bullish_reversal(cur: Candle, prev: Candle) -> bool:
        """Detect bullish reversal: hammer / bullish engulfing."""
        body = abs(cur.close - cur.open)
        lower_wick = min(cur.open, cur.close) - cur.low
        # Hammer: long lower wick, small body
        if lower_wick > body * 2 and cur.close > cur.open:
            return True
        # Bullish engulfing
        if prev.close < prev.open and cur.close > cur.open:
            if cur.close > prev.open and cur.open < prev.close:
                return True
        return False

    @staticmethod
    def _is_bearish_reversal(cur: Candle, prev: Candle) -> bool:
        """Detect bearish reversal: shooting star / bearish engulfing."""
        body = abs(cur.close - cur.open)
        upper_wick = cur.high - max(cur.open, cur.close)
        # Shooting star: long upper wick, small body
        if upper_wick > body * 2 and cur.close < cur.open:
            return True
        # Bearish engulfing
        if prev.close > prev.open and cur.close < cur.open:
            if cur.open > prev.close and cur.close < prev.open:
                return True
        return False

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
