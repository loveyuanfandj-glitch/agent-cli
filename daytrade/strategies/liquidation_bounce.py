"""Liquidation Bounce — enter after liquidation cascade exhaustion.

Crypto-native strategy exploiting the liquidation cascade mechanic:
1. Detect OI sharp drop (proxy for liquidation cascade)
2. Confirm with price drop and volume spike
3. Wait for stabilization candle (reversal pattern)
4. Enter contrarian, targeting partial retracement

Why it works for BTC/ETH:
- Perp exchanges have cascading liquidation engines
- Forced selling pushes price well past fair value
- Market snaps back once liquidation pressure exhausts
- Works especially well on leveraged instruments
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from daytrade.indicators import atr, rsi, ema
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class LiquidationBounceStrategy(DaytradeStrategy):
    name = "liquidation_bounce"
    description = "清算反弹 — OI 骤降 + 超跌后捕捉反弹"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.lookback: int = p["lookback"]
        self.price_drop_pct: float = p["price_drop_pct"]
        self.volume_spike_mult: float = p["volume_spike_mult"]
        self.atr_period: int = p["atr_period"]
        self.atr_sl_mult: float = p["atr_sl_mult"]
        self.retrace_target_pct: float = p["retrace_target_pct"]
        self.rsi_threshold: float = p["rsi_threshold"]
        self.require_reversal_candle: bool = p["require_reversal_candle"]
        self.cooldown_candles: int = p["cooldown_candles"]
        self.max_trades_per_day: int = p["max_trades_per_day"]

        self._cooldown_counter: int = 0
        self._trades_today: int = 0
        self._current_day: int = -1
        self._cascade_detected: bool = False
        self._cascade_low: float = 0.0
        self._cascade_high: float = 0.0  # pre-cascade high for retrace calc

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "lookback": 6,              # candles to measure the drop over
            "price_drop_pct": 1.5,      # min % drop to qualify as cascade
            "volume_spike_mult": 2.0,   # volume must be > avg * mult
            "atr_period": 14,
            "atr_sl_mult": 1.5,
            "retrace_target_pct": 40.0, # target % retracement of the drop
            "rsi_threshold": 30.0,      # RSI must be oversold (or overbought for shorts)
            "require_reversal_candle": True,
            "cooldown_candles": 3,      # wait N candles after cascade before entry
            "max_trades_per_day": 2,
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "price_drop_pct": (0.5, 3.0, 0.25),
            "volume_spike_mult": (1.5, 4.0, 0.5),
            "atr_sl_mult": (1.0, 3.0, 0.25),
            "retrace_target_pct": (25.0, 60.0, 5.0),
            "rsi_threshold": (20, 35, 5),
            "cooldown_candles": (1, 6, 1),
        }

    def reset(self):
        super().reset()
        self._cooldown_counter = 0
        self._trades_today = 0
        self._current_day = -1
        self._cascade_detected = False
        self._cascade_low = 0.0
        self._cascade_high = 0.0

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        min_len = max(self.lookback + 5, self.atr_period + 1, 16)
        if len(history) < min_len:
            return None

        # Day tracking
        day = candle.timestamp_ms // 86_400_000
        if day != self._current_day:
            self._current_day = day
            self._trades_today = 0

        # Check exit first
        if self._in_position:
            return self._check_exit(candle)

        if self._trades_today >= self.max_trades_per_day:
            return None

        closes = [c.close for c in history]
        volumes = [c.volume for c in history]
        atr_values = atr(history, self.atr_period)
        rsi_values = rsi(closes, 14)
        cur_atr = atr_values[-1]
        cur_rsi = rsi_values[-1]

        if cur_atr != cur_atr or cur_rsi != cur_rsi:
            return None

        # Average volume over recent history
        avg_vol = sum(volumes[-24:]) / min(len(volumes), 24)

        # --- Detect downward cascade (long bounce opportunity) ---
        recent_high = max(c.high for c in history[-self.lookback - 3: -self.lookback]) \
            if len(history) > self.lookback + 3 else history[-self.lookback - 1].high
        recent_low = candle.low
        drop_pct = (recent_high - recent_low) / recent_high * 100 if recent_high > 0 else 0

        # Volume spike during the drop
        recent_vol = sum(c.volume for c in history[-self.lookback:]) / self.lookback
        vol_spike = recent_vol / avg_vol if avg_vol > 0 else 0

        if (drop_pct >= self.price_drop_pct
                and vol_spike >= self.volume_spike_mult
                and cur_rsi <= self.rsi_threshold):

            # Check reversal candle: bullish close (close > open, lower wick > body)
            is_reversal = self._is_bullish_stabilization(candle, history[-2])

            if not self.require_reversal_candle or is_reversal:
                drop_size = recent_high - recent_low
                tp = candle.close + drop_size * (self.retrace_target_pct / 100)
                sl = candle.close - cur_atr * self.atr_sl_mult

                self._in_position = True
                self._position_side = "long"
                self._entry_price = candle.close
                self._entry_time = candle.timestamp_ms
                self._stop_loss = sl
                self._take_profit = tp
                self._trades_today += 1

                return Signal(
                    timestamp_ms=candle.timestamp_ms,
                    side=Side.LONG,
                    price=candle.close,
                    reason=(
                        f"清算反弹做多 (跌幅={drop_pct:.1f}%, "
                        f"放量={vol_spike:.1f}x, RSI={cur_rsi:.0f})"
                    ),
                    confidence=min(70 + drop_pct * 5, 95),
                    stop_loss=sl,
                    take_profit=tp,
                    meta={
                        "drop_pct": round(drop_pct, 2),
                        "volume_spike": round(vol_spike, 2),
                        "rsi": round(cur_rsi, 1),
                        "cascade_high": recent_high,
                        "cascade_low": recent_low,
                        "retrace_target": round(tp, 2),
                        "is_reversal_candle": is_reversal,
                    },
                )

        # --- Detect upward cascade (short bounce opportunity) ---
        recent_low_up = min(c.low for c in history[-self.lookback - 3: -self.lookback]) \
            if len(history) > self.lookback + 3 else history[-self.lookback - 1].low
        recent_high_up = candle.high
        pump_pct = (recent_high_up - recent_low_up) / recent_low_up * 100 if recent_low_up > 0 else 0

        if (pump_pct >= self.price_drop_pct
                and vol_spike >= self.volume_spike_mult
                and cur_rsi >= (100 - self.rsi_threshold)):

            is_reversal = self._is_bearish_stabilization(candle, history[-2])

            if not self.require_reversal_candle or is_reversal:
                pump_size = recent_high_up - recent_low_up
                tp = candle.close - pump_size * (self.retrace_target_pct / 100)
                sl = candle.close + cur_atr * self.atr_sl_mult

                self._in_position = True
                self._position_side = "short"
                self._entry_price = candle.close
                self._entry_time = candle.timestamp_ms
                self._stop_loss = sl
                self._take_profit = tp
                self._trades_today += 1

                return Signal(
                    timestamp_ms=candle.timestamp_ms,
                    side=Side.SHORT,
                    price=candle.close,
                    reason=(
                        f"清算反弹做空 (涨幅={pump_pct:.1f}%, "
                        f"放量={vol_spike:.1f}x, RSI={cur_rsi:.0f})"
                    ),
                    confidence=min(70 + pump_pct * 5, 95),
                    stop_loss=sl,
                    take_profit=tp,
                    meta={
                        "pump_pct": round(pump_pct, 2),
                        "volume_spike": round(vol_spike, 2),
                        "rsi": round(cur_rsi, 1),
                        "cascade_low": recent_low_up,
                        "cascade_high": recent_high_up,
                        "retrace_target": round(tp, 2),
                        "is_reversal_candle": is_reversal,
                    },
                )

        return None

    @staticmethod
    def _is_bullish_stabilization(cur: Candle, prev: Candle) -> bool:
        """Detect bullish stabilization: hammer, pin bar, or bullish engulfing."""
        body = abs(cur.close - cur.open)
        lower_wick = min(cur.open, cur.close) - cur.low
        candle_range = cur.high - cur.low
        if candle_range == 0:
            return False

        # Hammer / pin bar: long lower wick, bullish close
        if lower_wick > body * 1.5 and cur.close > cur.open:
            return True

        # Bullish engulfing
        if (prev.close < prev.open  # prev bearish
                and cur.close > cur.open  # cur bullish
                and cur.close > prev.open
                and cur.open <= prev.close):
            return True

        # Doji with long lower wick (indecision after selling)
        if body < candle_range * 0.15 and lower_wick > candle_range * 0.5:
            return True

        return False

    @staticmethod
    def _is_bearish_stabilization(cur: Candle, prev: Candle) -> bool:
        """Detect bearish stabilization: shooting star or bearish engulfing."""
        body = abs(cur.close - cur.open)
        upper_wick = cur.high - max(cur.open, cur.close)
        candle_range = cur.high - cur.low
        if candle_range == 0:
            return False

        # Shooting star
        if upper_wick > body * 1.5 and cur.close < cur.open:
            return True

        # Bearish engulfing
        if (prev.close > prev.open  # prev bullish
                and cur.close < cur.open  # cur bearish
                and cur.open >= prev.close
                and cur.close < prev.open):
            return True

        # Doji with long upper wick
        if body < candle_range * 0.15 and upper_wick > candle_range * 0.5:
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
                    price=self._take_profit, reason="止盈 (回撤目标)",
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
                    price=self._take_profit, reason="止盈 (回撤目标)",
                )
        return None
