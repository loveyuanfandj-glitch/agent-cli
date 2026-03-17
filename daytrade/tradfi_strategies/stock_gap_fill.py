"""Gap Fill — trade overnight gap fill on individual stocks.

Stocks frequently gap up/down overnight then fill the gap during the session.
Gap fill rate is ~60-70% for gaps < 2%, especially on liquid mega-caps.

Logic:
1. Detect overnight gap (first candle vs previous day's close)
2. Wait for initial momentum to exhaust (don't fade immediately)
3. Enter in gap-fill direction after 2-3 candles of stabilization
4. Target = previous close (full gap fill), SL = gap extension
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import atr
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class GapFillStrategy(DaytradeStrategy):
    name = "stock_gap_fill"
    description = "缺口回补 — 隔夜跳空后日内回补"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.min_gap_pct: float = p["min_gap_pct"]
        self.max_gap_pct: float = p["max_gap_pct"]
        self.wait_candles: int = p["wait_candles"]
        self.atr_period: int = p["atr_period"]
        self.atr_sl_mult: float = p["atr_sl_mult"]
        self.fill_target_pct: float = p["fill_target_pct"]

        self._current_day: int = -1
        self._prev_day_close: float = 0.0
        self._gap_detected: bool = False
        self._gap_direction: str = ""  # "up" or "down"
        self._gap_open: float = 0.0
        self._session_candle: int = 0
        self._traded_today: bool = False

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "min_gap_pct": 0.3,      # minimum gap % to trade
            "max_gap_pct": 3.0,      # skip extreme gaps (news-driven)
            "wait_candles": 2,       # wait N candles before entry
            "atr_period": 14,
            "atr_sl_mult": 1.5,
            "fill_target_pct": 80.0, # target % of gap filled (80% = near full)
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "min_gap_pct": (0.2, 1.0, 0.1),
            "max_gap_pct": (1.5, 5.0, 0.5),
            "wait_candles": (1, 5, 1),
            "atr_sl_mult": (1.0, 3.0, 0.25),
            "fill_target_pct": (50, 100, 10),
        }

    def reset(self):
        super().reset()
        self._current_day = -1
        self._prev_day_close = 0.0
        self._gap_detected = False
        self._gap_direction = ""
        self._gap_open = 0.0
        self._session_candle = 0
        self._traded_today = False

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        day = candle.timestamp_ms // 86_400_000

        # New day
        if day != self._current_day:
            if self._current_day != -1 and history:
                # Find previous day's last candle
                for c in reversed(history[:-1]):
                    if c.timestamp_ms // 86_400_000 != day:
                        self._prev_day_close = c.close
                        break

            self._current_day = day
            self._gap_detected = False
            self._gap_direction = ""
            self._session_candle = 0
            self._traded_today = False

        self._session_candle += 1

        if self._in_position:
            return self._check_exit(candle)

        if self._traded_today:
            return None

        # Detect gap on first candle of day
        if self._session_candle == 1 and self._prev_day_close > 0:
            gap_pct = (candle.open - self._prev_day_close) / self._prev_day_close * 100

            if abs(gap_pct) >= self.min_gap_pct and abs(gap_pct) <= self.max_gap_pct:
                self._gap_detected = True
                self._gap_direction = "up" if gap_pct > 0 else "down"
                self._gap_open = candle.open
            return None

        # Wait for stabilization, then enter
        if (self._gap_detected
                and self._session_candle == self.wait_candles + 1
                and not self._traded_today):

            if len(history) < self.atr_period + 1:
                return None

            atr_vals = atr(history, self.atr_period)
            cur_atr = atr_vals[-1]
            if cur_atr != cur_atr:
                return None

            gap_size = abs(self._gap_open - self._prev_day_close)
            fill_target = gap_size * (self.fill_target_pct / 100)

            # Gap up → fade short (expect fill down to prev close)
            if self._gap_direction == "up":
                tp = candle.close - fill_target
                sl = candle.close + cur_atr * self.atr_sl_mult
                self._in_position = True
                self._position_side = "short"
                self._entry_price = candle.close
                self._entry_time = candle.timestamp_ms
                self._stop_loss = sl
                self._take_profit = tp
                self._traded_today = True
                return Signal(
                    timestamp_ms=candle.timestamp_ms, side=Side.SHORT, price=candle.close,
                    reason=f"缺口回补做空 (跳空+{gap_size / self._prev_day_close * 100:.1f}%)",
                    confidence=65, stop_loss=sl, take_profit=tp,
                    meta={"gap_pct": round(gap_size / self._prev_day_close * 100, 2),
                          "prev_close": self._prev_day_close, "gap_open": self._gap_open},
                )

            # Gap down → fade long (expect fill up to prev close)
            if self._gap_direction == "down":
                tp = candle.close + fill_target
                sl = candle.close - cur_atr * self.atr_sl_mult
                self._in_position = True
                self._position_side = "long"
                self._entry_price = candle.close
                self._entry_time = candle.timestamp_ms
                self._stop_loss = sl
                self._take_profit = tp
                self._traded_today = True
                return Signal(
                    timestamp_ms=candle.timestamp_ms, side=Side.LONG, price=candle.close,
                    reason=f"缺口回补做多 (跳空-{gap_size / self._prev_day_close * 100:.1f}%)",
                    confidence=65, stop_loss=sl, take_profit=tp,
                    meta={"gap_pct": round(gap_size / self._prev_day_close * 100, 2),
                          "prev_close": self._prev_day_close, "gap_open": self._gap_open},
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
                              price=self._take_profit, reason="止盈 (缺口回补)")
        else:
            if candle.high >= self._stop_loss:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                              price=self._stop_loss, reason="止损")
            if candle.low <= self._take_profit:
                self._in_position = False
                return Signal(timestamp_ms=candle.timestamp_ms, side=Side.SHORT,
                              price=self._take_profit, reason="止盈 (缺口回补)")
        return None
