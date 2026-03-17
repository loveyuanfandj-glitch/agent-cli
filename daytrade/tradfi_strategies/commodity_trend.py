"""Commodity Trend Following (Long-term) — ride macro trends on daily/weekly charts.

Commodities trend strongly on weekly/monthly timeframes due to supply-demand cycles.
Uses dual MA crossover + ADX filter for trend confirmation.
Wide trailing stop (3x ATR) to stay in position through noise.
Typical holding period: weeks to months.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import ema, sma, atr
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


def _adx_proxy(candles: List[Candle], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    moves = []
    for i in range(-period, 0):
        move = abs(candles[i].close - candles[i - 1].close)
        rng = candles[i].high - candles[i].low
        moves.append(move / rng if rng > 0 else 0)
    return min(sum(moves) / len(moves) * 100, 100)


class CommodityTrendStrategy(DaytradeStrategy):
    name = "commodity_trend"
    description = "商品趋势跟随 — 周线级别 MA 交叉 + ADX 过滤，宽幅追踪止损"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.fast_ma: int = p["fast_ma"]
        self.slow_ma: int = p["slow_ma"]
        self.adx_threshold: float = p["adx_threshold"]
        self.atr_period: int = p["atr_period"]
        self.trail_atr_mult: float = p["trail_atr_mult"]

        self._trailing_stop: float = 0.0
        self._best_price: float = 0.0

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "fast_ma": 20,           # ~1 month on daily
            "slow_ma": 50,           # ~2.5 months on daily
            "adx_threshold": 20.0,
            "atr_period": 14,
            "trail_atr_mult": 3.0,   # wide stop for long-term
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "fast_ma": (10, 30, 5),
            "slow_ma": (30, 100, 10),
            "adx_threshold": (15, 30, 5),
            "trail_atr_mult": (2.0, 5.0, 0.5),
        }

    def reset(self):
        super().reset()
        self._trailing_stop = 0.0
        self._best_price = 0.0

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        min_len = max(self.slow_ma + 2, self.atr_period + 1)
        if len(history) < min_len:
            return None

        closes = [c.close for c in history]
        fast = sma(closes, self.fast_ma)
        slow = sma(closes, self.slow_ma)
        atr_vals = atr(history, self.atr_period)
        cur_atr = atr_vals[-1]

        if cur_atr != cur_atr or fast[-1] != fast[-1] or slow[-1] != slow[-1]:
            return None

        adx = _adx_proxy(history, 14)

        if self._in_position:
            return self._check_exit(candle, cur_atr)

        if adx < self.adx_threshold:
            return None

        # Golden cross
        if fast[-2] <= slow[-2] and fast[-1] > slow[-1]:
            sl = candle.close - cur_atr * self.trail_atr_mult
            self._in_position = True
            self._position_side = "long"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = 0  # no fixed TP, use trailing stop
            self._trailing_stop = sl
            self._best_price = candle.close
            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.LONG, price=candle.close,
                reason=f"趋势做多: MA{self.fast_ma} 上穿 MA{self.slow_ma} (ADX={adx:.0f})",
                confidence=min(50 + adx, 90), stop_loss=sl,
                meta={"adx": round(adx, 1), "fast_ma": fast[-1], "slow_ma": slow[-1]},
            )

        # Death cross
        if fast[-2] >= slow[-2] and fast[-1] < slow[-1]:
            sl = candle.close + cur_atr * self.trail_atr_mult
            self._in_position = True
            self._position_side = "short"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = 0
            self._trailing_stop = sl
            self._best_price = candle.close
            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.SHORT, price=candle.close,
                reason=f"趋势做空: MA{self.fast_ma} 下穿 MA{self.slow_ma} (ADX={adx:.0f})",
                confidence=min(50 + adx, 90), stop_loss=sl,
                meta={"adx": round(adx, 1), "fast_ma": fast[-1], "slow_ma": slow[-1]},
            )

        return None

    def _check_exit(self, candle: Candle, cur_atr: float) -> Optional[Signal]:
        if self._position_side == "long":
            if candle.high > self._best_price:
                self._best_price = candle.high
                self._trailing_stop = max(self._trailing_stop, self._best_price - cur_atr * self.trail_atr_mult)
            if candle.low <= self._trailing_stop:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                              price=max(self._trailing_stop, candle.low), reason="追踪止损出场")
        else:
            if candle.low < self._best_price:
                self._best_price = candle.low
                self._trailing_stop = min(self._trailing_stop, self._best_price + cur_atr * self.trail_atr_mult)
            if candle.high >= self._trailing_stop:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                              price=min(self._trailing_stop, candle.high), reason="追踪止损出场")
        return None
