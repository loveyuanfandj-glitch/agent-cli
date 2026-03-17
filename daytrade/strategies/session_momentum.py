"""Session Momentum — trend-following with pullback entries.

Detects strong intraday trends via EMA slope + MACD, enters on pullbacks
to fast EMA. Uses trailing stop once in profit.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import ema, macd, atr
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class SessionMomentumStrategy(DaytradeStrategy):
    name = "session_momentum"
    description = "Session 动量 — 趋势跟随 + 回调入场"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.fast_ema: int = p["fast_ema"]
        self.slow_ema: int = p["slow_ema"]
        self.pullback_pct: float = p["pullback_pct"]
        self.atr_period: int = p["atr_period"]
        self.trail_atr_mult: float = p["trail_atr_mult"]
        self.risk_reward: float = p["risk_reward"]
        self.min_slope_pct: float = p["min_slope_pct"]

        self._trailing_stop: float = 0.0
        self._best_price: float = 0.0

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "fast_ema": 9,
            "slow_ema": 21,
            "pullback_pct": 0.15,     # pullback to fast EMA within this %
            "atr_period": 14,
            "trail_atr_mult": 2.0,    # trailing stop = ATR * mult
            "risk_reward": 2.5,
            "min_slope_pct": 0.05,    # minimum EMA slope to confirm trend
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "fast_ema": (5, 15, 1),
            "slow_ema": (15, 50, 5),
            "pullback_pct": (0.05, 0.5, 0.05),
            "trail_atr_mult": (1.0, 3.0, 0.25),
            "risk_reward": (1.5, 4.0, 0.5),
        }

    def reset(self):
        super().reset()
        self._trailing_stop = 0.0
        self._best_price = 0.0

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        min_len = max(self.slow_ema + 5, self.atr_period + 1)
        if len(history) < min_len:
            return None

        closes = [c.close for c in history]
        fast = ema(closes, self.fast_ema)
        slow = ema(closes, self.slow_ema)
        atr_values = atr(history, self.atr_period)
        macd_line, signal_line, hist = macd(closes)

        cur_fast = fast[-1]
        cur_slow = slow[-1]
        cur_atr = atr_values[-1]
        prev_fast = fast[-2]

        if cur_atr != cur_atr:  # NaN
            return None

        # EMA slope
        slope_pct = (cur_fast - prev_fast) / prev_fast * 100 if prev_fast else 0

        # Check exit with trailing stop
        if self._in_position:
            return self._check_exit(candle, cur_atr)

        # Trend direction: fast > slow = bullish, fast < slow = bearish
        bullish = cur_fast > cur_slow and slope_pct > self.min_slope_pct
        bearish = cur_fast < cur_slow and slope_pct < -self.min_slope_pct

        # MACD confirmation
        macd_bull = macd_line[-1] > signal_line[-1]
        macd_bear = macd_line[-1] < signal_line[-1]

        # Pullback: price near fast EMA
        dist_to_fast = abs(candle.close - cur_fast) / cur_fast * 100

        if bullish and macd_bull and dist_to_fast < self.pullback_pct:
            sl = candle.close - cur_atr * self.trail_atr_mult
            tp = candle.close + (candle.close - sl) * self.risk_reward
            self._in_position = True
            self._position_side = "long"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = tp
            self._trailing_stop = sl
            self._best_price = candle.close
            return Signal(
                timestamp_ms=candle.timestamp_ms,
                side=Side.LONG,
                price=candle.close,
                reason=f"动量回调做多 (slope={slope_pct:.3f}%)",
                confidence=75,
                stop_loss=sl,
                take_profit=tp,
                meta={"slope": slope_pct, "dist_to_ema": dist_to_fast},
            )

        if bearish and macd_bear and dist_to_fast < self.pullback_pct:
            sl = candle.close + cur_atr * self.trail_atr_mult
            tp = candle.close - (sl - candle.close) * self.risk_reward
            self._in_position = True
            self._position_side = "short"
            self._entry_price = candle.close
            self._entry_time = candle.timestamp_ms
            self._stop_loss = sl
            self._take_profit = tp
            self._trailing_stop = sl
            self._best_price = candle.close
            return Signal(
                timestamp_ms=candle.timestamp_ms,
                side=Side.SHORT,
                price=candle.close,
                reason=f"动量回调做空 (slope={slope_pct:.3f}%)",
                confidence=75,
                stop_loss=sl,
                take_profit=tp,
                meta={"slope": slope_pct, "dist_to_ema": dist_to_fast},
            )

        return None

    def _check_exit(self, candle: Candle, cur_atr: float) -> Optional[Signal]:
        # Update trailing stop
        if self._position_side == "long":
            if candle.high > self._best_price:
                self._best_price = candle.high
                new_trail = self._best_price - cur_atr * self.trail_atr_mult
                self._trailing_stop = max(self._trailing_stop, new_trail)
            if candle.low <= self._trailing_stop:
                self._in_position = False
                price = max(self._trailing_stop, candle.low)
                return Signal(
                    timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                    price=price, reason="追踪止损",
                )
            if candle.high >= self._take_profit:
                self._in_position = False
                return Signal(
                    timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                    price=self._take_profit, reason="止盈",
                )
        else:
            if candle.low < self._best_price:
                self._best_price = candle.low
                new_trail = self._best_price + cur_atr * self.trail_atr_mult
                self._trailing_stop = min(self._trailing_stop, new_trail)
            if candle.high >= self._trailing_stop:
                self._in_position = False
                price = min(self._trailing_stop, candle.high)
                return Signal(
                    timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                    price=price, reason="追踪止损",
                )
            if candle.low <= self._take_profit:
                self._in_position = False
                return Signal(
                    timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                    price=self._take_profit, reason="止盈",
                )
        return None
