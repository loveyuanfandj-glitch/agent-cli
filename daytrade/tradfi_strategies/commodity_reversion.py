"""Commodity Mean Reversion — Bollinger Band extremes + RSI divergence.

When commodities hit BB extremes with RSI confirmation, they tend to snap back.
Best in ranging / choppy markets. Uses tighter stops than trend strategy.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import rsi, bollinger_bands, atr
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class CommodityReversionStrategy(DaytradeStrategy):
    name = "commodity_reversion"
    description = "商品均值回归 — 布林带极端 + RSI 确认反转"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.bb_period: int = p["bb_period"]
        self.bb_std: float = p["bb_std"]
        self.rsi_period: int = p["rsi_period"]
        self.rsi_ob: float = p["rsi_ob"]
        self.rsi_os: float = p["rsi_os"]
        self.atr_period: int = p["atr_period"]
        self.atr_sl_mult: float = p["atr_sl_mult"]
        self.risk_reward: float = p["risk_reward"]

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "bb_period": 20, "bb_std": 2.0,
            "rsi_period": 14, "rsi_ob": 70.0, "rsi_os": 30.0,
            "atr_period": 14, "atr_sl_mult": 1.5, "risk_reward": 2.0,
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "bb_std": (1.5, 3.0, 0.25), "rsi_ob": (65, 80, 5),
            "rsi_os": (20, 35, 5), "atr_sl_mult": (1.0, 3.0, 0.25),
            "risk_reward": (1.5, 3.5, 0.5),
        }

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        min_len = max(self.bb_period + 1, self.rsi_period + 2, self.atr_period + 1)
        if len(history) < min_len:
            return None

        if self._in_position:
            return self._check_exit(candle)

        closes = [c.close for c in history]
        upper, mid, lower = bollinger_bands(closes, self.bb_period, self.bb_std)
        rsi_vals = rsi(closes, self.rsi_period)
        atr_vals = atr(history, self.atr_period)
        cur_rsi = rsi_vals[-1]
        prev_rsi = rsi_vals[-2]
        cur_atr = atr_vals[-1]

        if cur_rsi != cur_rsi or cur_atr != cur_atr:
            return None

        # Long: price at lower BB + RSI oversold turning up
        if candle.close <= lower[-1] and prev_rsi < self.rsi_os and cur_rsi > prev_rsi:
            sl = candle.close - cur_atr * self.atr_sl_mult
            tp = mid[-1]  # target = BB midline
            risk = candle.close - sl
            if risk > 0:
                tp = max(tp, candle.close + risk * self.risk_reward)
            self._in_position = True
            self._position_side = "long"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = tp
            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.LONG, price=candle.close,
                reason=f"商品均值回归做多 (RSI={cur_rsi:.0f}, 触及BB下轨)",
                confidence=70, stop_loss=sl, take_profit=tp,
                meta={"rsi": cur_rsi, "bb_lower": lower[-1], "bb_mid": mid[-1]},
            )

        # Short: price at upper BB + RSI overbought turning down
        if candle.close >= upper[-1] and prev_rsi > self.rsi_ob and cur_rsi < prev_rsi:
            sl = candle.close + cur_atr * self.atr_sl_mult
            tp = mid[-1]
            risk = sl - candle.close
            if risk > 0:
                tp = min(tp, candle.close - risk * self.risk_reward)
            self._in_position = True
            self._position_side = "short"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = tp
            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.SHORT, price=candle.close,
                reason=f"商品均值回归做空 (RSI={cur_rsi:.0f}, 触及BB上轨)",
                confidence=70, stop_loss=sl, take_profit=tp,
                meta={"rsi": cur_rsi, "bb_upper": upper[-1], "bb_mid": mid[-1]},
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
                              price=self._take_profit, reason="止盈 (回归中轨)")
        else:
            if candle.high >= self._stop_loss:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                              price=self._stop_loss, reason="止损")
            if candle.low <= self._take_profit:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                              price=self._take_profit, reason="止盈 (回归中轨)")
        return None
