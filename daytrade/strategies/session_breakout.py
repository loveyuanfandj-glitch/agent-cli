"""Session Range Breakout — trade breakout of the Asian session range.

Crypto-native intraday strategy:
1. Define a range from the Asian session (00:00-08:00 UTC)
2. Wait for Europe/US session (08:00-21:00 UTC) for breakout
3. Require volume confirmation to filter false breakouts
4. ATR-based stops, max 1-2 trades per day

Why it works for BTC/ETH:
- Asian session is typically low-volatility consolidation
- Europe/US sessions bring institutional flow and directional moves
- The Asian range acts as a natural support/resistance zone
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import atr, ema
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy

# Session boundaries (UTC hours)
ASIA_START_H = 0
ASIA_END_H = 8
TRADE_END_H = 21  # stop opening new positions after 21:00 UTC


def _utc_hour(ts_ms: int) -> int:
    """Extract UTC hour from timestamp in ms."""
    return (ts_ms // 3_600_000) % 24


class SessionBreakoutStrategy(DaytradeStrategy):
    name = "session_breakout"
    description = "时段区间突破 — 亚盘定区间，欧美盘突破入场"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.atr_period: int = p["atr_period"]
        self.atr_sl_mult: float = p["atr_sl_mult"]
        self.risk_reward: float = p["risk_reward"]
        self.volume_confirm: bool = p["volume_confirm"]
        self.volume_mult: float = p["volume_mult"]
        self.breakout_buffer_pct: float = p["breakout_buffer_pct"]
        self.max_trades_per_day: int = p["max_trades_per_day"]
        self.use_ema_filter: bool = p["use_ema_filter"]
        self.ema_period: int = p["ema_period"]

        # Session state
        self._current_day: int = -1
        self._asia_high: float = 0.0
        self._asia_low: float = float("inf")
        self._asia_complete: bool = False
        self._trades_today: int = 0
        self._avg_volume: float = 0.0

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "atr_period": 14,
            "atr_sl_mult": 1.5,
            "risk_reward": 2.0,
            "volume_confirm": True,
            "volume_mult": 1.5,        # breakout candle vol > avg * mult
            "breakout_buffer_pct": 0.05,  # price must exceed range by this %
            "max_trades_per_day": 2,
            "use_ema_filter": True,     # only long above EMA, short below
            "ema_period": 50,
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "atr_sl_mult": (1.0, 3.0, 0.25),
            "risk_reward": (1.5, 4.0, 0.5),
            "volume_mult": (1.0, 3.0, 0.25),
            "breakout_buffer_pct": (0.0, 0.2, 0.025),
            "max_trades_per_day": (1, 3, 1),
        }

    def reset(self):
        super().reset()
        self._current_day = -1
        self._asia_high = 0.0
        self._asia_low = float("inf")
        self._asia_complete = False
        self._trades_today = 0
        self._avg_volume = 0.0

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        day = candle.timestamp_ms // 86_400_000
        hour = _utc_hour(candle.timestamp_ms)

        # New day — reset session state
        if day != self._current_day:
            self._current_day = day
            self._asia_high = 0.0
            self._asia_low = float("inf")
            self._asia_complete = False
            self._trades_today = 0

        # Phase 1: Build Asian session range (00:00-08:00 UTC)
        if hour < ASIA_END_H:
            self._asia_high = max(self._asia_high, candle.high)
            self._asia_low = min(self._asia_low, candle.low)
            return None

        # Mark Asian range as complete
        if not self._asia_complete:
            self._asia_complete = True
            # Sanity check
            if self._asia_high <= 0 or self._asia_low >= float("inf"):
                return None

        # Check exit first
        if self._in_position:
            return self._check_exit(candle)

        # Phase 2: Trade breakouts during Europe/US session
        if not self._asia_complete:
            return None
        if hour >= TRADE_END_H:
            return None  # too late in the day
        if self._trades_today >= self.max_trades_per_day:
            return None

        if len(history) < max(self.atr_period + 1, self.ema_period + 1):
            return None

        atr_values = atr(history, self.atr_period)
        cur_atr = atr_values[-1]
        if cur_atr != cur_atr:  # NaN
            return None

        # Compute average volume for confirmation
        if len(history) >= 20:
            self._avg_volume = sum(c.volume for c in history[-20:]) / 20

        # Volume filter
        vol_ok = True
        if self.volume_confirm and self._avg_volume > 0:
            vol_ok = candle.volume >= self._avg_volume * self.volume_mult

        # EMA trend filter
        ema_ok_long = True
        ema_ok_short = True
        if self.use_ema_filter:
            closes = [c.close for c in history]
            ema_values = ema(closes, self.ema_period)
            ema_ok_long = candle.close > ema_values[-1]
            ema_ok_short = candle.close < ema_values[-1]

        # Breakout buffer
        buffer = self._asia_high * self.breakout_buffer_pct / 100
        range_width = self._asia_high - self._asia_low

        # Breakout above Asian high
        if candle.close > self._asia_high + buffer and vol_ok and ema_ok_long:
            sl = max(candle.close - cur_atr * self.atr_sl_mult, self._asia_low)
            risk = candle.close - sl
            tp = candle.close + risk * self.risk_reward

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
                reason=f"亚盘区间突破做多 (>{self._asia_high:.2f}, 区间宽度={range_width:.2f})",
                confidence=75,
                stop_loss=sl,
                take_profit=tp,
                meta={
                    "asia_high": self._asia_high,
                    "asia_low": self._asia_low,
                    "range_width": range_width,
                    "session_hour": hour,
                    "volume_ratio": candle.volume / self._avg_volume if self._avg_volume else 0,
                },
            )

        # Breakout below Asian low
        if candle.close < self._asia_low - buffer and vol_ok and ema_ok_short:
            sl = min(candle.close + cur_atr * self.atr_sl_mult, self._asia_high)
            risk = sl - candle.close
            tp = candle.close - risk * self.risk_reward

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
                reason=f"亚盘区间跌破做空 (<{self._asia_low:.2f}, 区间宽度={range_width:.2f})",
                confidence=75,
                stop_loss=sl,
                take_profit=tp,
                meta={
                    "asia_high": self._asia_high,
                    "asia_low": self._asia_low,
                    "range_width": range_width,
                    "session_hour": hour,
                    "volume_ratio": candle.volume / self._avg_volume if self._avg_volume else 0,
                },
            )

        return None

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
