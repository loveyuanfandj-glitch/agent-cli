"""Commodity Trend Following — EMA trend + ADX strength filter.

Commodities (gold, silver, oil) trend strongly due to macro flows.
Uses dual EMA for direction + ADX proxy for trend strength.
Trailing stop via ATR to let winners run.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import ema, atr, rsi
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


def _adx_proxy(candles: List[Candle], period: int = 14) -> float:
    """Simplified ADX proxy: average directional movement over period.

    Uses absolute price changes relative to ATR to estimate trend strength.
    Returns 0-100 scale (>25 = trending, <20 = ranging).
    """
    if len(candles) < period + 1:
        return 0.0

    directional_moves = []
    for i in range(-period, 0):
        move = abs(candles[i].close - candles[i - 1].close)
        candle_range = candles[i].high - candles[i].low
        if candle_range > 0:
            directional_moves.append(move / candle_range)
        else:
            directional_moves.append(0)

    avg_dm = sum(directional_moves) / len(directional_moves) if directional_moves else 0
    return min(avg_dm * 100, 100)


class CommodityTrendStrategy(DaytradeStrategy):
    name = "commodity_trend"
    description = "商品趋势跟随 — EMA+ADX 趋势过滤，ATR 追踪止损"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.fast_ema: int = p["fast_ema"]
        self.slow_ema: int = p["slow_ema"]
        self.adx_threshold: float = p["adx_threshold"]
        self.atr_period: int = p["atr_period"]
        self.trail_atr_mult: float = p["trail_atr_mult"]
        self.risk_reward: float = p["risk_reward"]

        self._trailing_stop: float = 0.0
        self._best_price: float = 0.0

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "fast_ema": 10,
            "slow_ema": 30,
            "adx_threshold": 25.0,
            "atr_period": 14,
            "trail_atr_mult": 2.5,
            "risk_reward": 2.5,
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "fast_ema": (5, 20, 1),
            "slow_ema": (20, 60, 5),
            "adx_threshold": (15, 35, 5),
            "trail_atr_mult": (1.5, 4.0, 0.5),
            "risk_reward": (1.5, 4.0, 0.5),
        }

    def reset(self):
        super().reset()
        self._trailing_stop = 0.0
        self._best_price = 0.0

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        min_len = max(self.slow_ema + 2, self.atr_period + 1, 20)
        if len(history) < min_len:
            return None

        closes = [c.close for c in history]
        fast = ema(closes, self.fast_ema)
        slow = ema(closes, self.slow_ema)
        atr_values = atr(history, self.atr_period)
        cur_atr = atr_values[-1]
        if cur_atr != cur_atr:
            return None

        adx = _adx_proxy(history, 14)
        prev_fast_above = fast[-2] > slow[-2]
        cur_fast_above = fast[-1] > slow[-1]

        if self._in_position:
            return self._check_exit(candle, cur_atr)

        # Only trade when ADX shows trending market
        if adx < self.adx_threshold:
            return None

        # Bullish crossover
        if cur_fast_above and not prev_fast_above:
            sl = candle.close - cur_atr * self.trail_atr_mult
            tp = candle.close + (candle.close - sl) * self.risk_reward
            self._enter("long", candle, sl, tp)
            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.LONG, price=candle.close,
                reason=f"商品趋势做多 (ADX={adx:.0f})",
                confidence=min(50 + adx, 90), stop_loss=sl, take_profit=tp,
                meta={"adx": round(adx, 1), "fast_ema": fast[-1], "slow_ema": slow[-1]},
            )

        # Bearish crossover
        if not cur_fast_above and prev_fast_above:
            sl = candle.close + cur_atr * self.trail_atr_mult
            tp = candle.close - (sl - candle.close) * self.risk_reward
            self._enter("short", candle, sl, tp)
            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.SHORT, price=candle.close,
                reason=f"商品趋势做空 (ADX={adx:.0f})",
                confidence=min(50 + adx, 90), stop_loss=sl, take_profit=tp,
                meta={"adx": round(adx, 1), "fast_ema": fast[-1], "slow_ema": slow[-1]},
            )

        return None

    def _enter(self, side: str, candle: Candle, sl: float, tp: float):
        self._in_position = True
        self._position_side = side
        self._entry_price = candle.close
        self._entry_time = candle.timestamp_ms
        self._stop_loss = sl
        self._take_profit = tp
        self._trailing_stop = sl
        self._best_price = candle.close

    def _check_exit(self, candle: Candle, cur_atr: float) -> Optional[Signal]:
        if self._position_side == "long":
            if candle.high > self._best_price:
                self._best_price = candle.high
                self._trailing_stop = max(self._trailing_stop,
                                          self._best_price - cur_atr * self.trail_atr_mult)
            if candle.low <= self._trailing_stop:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                              price=max(self._trailing_stop, candle.low), reason="追踪止损")
            if candle.high >= self._take_profit:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                              price=self._take_profit, reason="止盈")
        else:
            if candle.low < self._best_price:
                self._best_price = candle.low
                self._trailing_stop = min(self._trailing_stop,
                                          self._best_price + cur_atr * self.trail_atr_mult)
            if candle.high >= self._trailing_stop:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                              price=min(self._trailing_stop, candle.high), reason="追踪止损")
            if candle.low <= self._take_profit:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                              price=self._take_profit, reason="止盈")
        return None
