"""Commodity Value Buy (Long-term) — buy deep pullbacks in long-term uptrends.

Commodities in secular uptrends (gold, silver) periodically pull back 10-20%.
This strategy buys when price drops to long-term support (200 SMA) with RSI oversold,
holds for the recovery. Typical holding: weeks to months.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import sma, rsi, atr
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class CommodityReversionStrategy(DaytradeStrategy):
    name = "commodity_reversion"
    description = "商品抄底 — 长期上升趋势中的深度回调买入"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.trend_ma: int = p["trend_ma"]
        self.pullback_pct: float = p["pullback_pct"]
        self.rsi_period: int = p["rsi_period"]
        self.rsi_threshold: float = p["rsi_threshold"]
        self.atr_period: int = p["atr_period"]
        self.atr_sl_mult: float = p["atr_sl_mult"]
        self.target_pct: float = p["target_pct"]

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "trend_ma": 200,          # long-term trend
            "pullback_pct": 5.0,      # % below recent high to trigger
            "rsi_period": 14,
            "rsi_threshold": 35.0,    # RSI must be below this
            "atr_period": 14,
            "atr_sl_mult": 3.0,
            "target_pct": 10.0,       # target % recovery from entry
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "trend_ma": (100, 250, 50),
            "pullback_pct": (3.0, 15.0, 1.0),
            "rsi_threshold": (25, 40, 5),
            "atr_sl_mult": (2.0, 5.0, 0.5),
            "target_pct": (5.0, 20.0, 2.5),
        }

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        min_len = max(self.trend_ma + 1, self.rsi_period + 2, self.atr_period + 1, 50)
        if len(history) < min_len:
            return None

        if self._in_position:
            return self._check_exit(candle)

        closes = [c.close for c in history]
        trend = sma(closes, self.trend_ma)
        rsi_vals = rsi(closes, self.rsi_period)
        atr_vals = atr(history, self.atr_period)

        cur_trend = trend[-1]
        cur_rsi = rsi_vals[-1]
        cur_atr = atr_vals[-1]

        if cur_trend != cur_trend or cur_rsi != cur_rsi or cur_atr != cur_atr:
            return None

        # Only buy in uptrend: price was above 200 SMA recently
        above_trend_recently = any(c.close > cur_trend for c in history[-50:])
        if not above_trend_recently:
            return None

        # Measure pullback from recent high (last 50 candles)
        recent_high = max(c.high for c in history[-50:])
        pullback = (recent_high - candle.close) / recent_high * 100

        # Buy conditions: deep pullback + RSI oversold + price near/below trend MA
        if pullback >= self.pullback_pct and cur_rsi <= self.rsi_threshold:
            sl = candle.close - cur_atr * self.atr_sl_mult
            tp = candle.close * (1 + self.target_pct / 100)
            self._in_position = True
            self._position_side = "long"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = tp
            return Signal(
                timestamp_ms=candle.timestamp_ms, side=Side.LONG, price=candle.close,
                reason=f"趋势回调抄底 (回撤={pullback:.1f}%, RSI={cur_rsi:.0f})",
                confidence=70, stop_loss=sl, take_profit=tp,
                meta={"pullback_pct": round(pullback, 1), "rsi": round(cur_rsi, 1),
                      "recent_high": recent_high, "trend_ma": cur_trend},
            )

        return None

    def _check_exit(self, candle: Candle) -> Optional[Signal]:
        if candle.low <= self._stop_loss:
            self._in_position = False
            return Signal(timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                          price=self._stop_loss, reason="止损")
        if candle.high >= self._take_profit:
            self._in_position = False
            return Signal(timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                          price=self._take_profit, reason=f"止盈 (+{self.target_pct}%)")
        return None
