"""AH Premium Convergence — trade H-share discount to A-share.

Many Chinese companies are dual-listed in Shanghai/Shenzhen (A-share)
and Hong Kong (H-share). H-shares typically trade at a discount.
When the discount becomes extreme, H-shares tend to converge.

This strategy monitors the AH premium ratio using the HSI AH Premium Index
proxy (computed from A/H price pairs) and trades mean reversion.

Since we can't easily get real-time A-share data from Yahoo Finance,
we use the H-share ETF (2828.HK) with its own price momentum and
RSI-based mean reversion as a proxy — when H-shares are beaten down
(RSI oversold + below long-term MA), they tend to rebound.

For direct AH premium tracking, use HSAHP index or 2828.HK vs 510300.SS
(沪深300 ETF) ratio.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from daytrade.indicators import sma, rsi, atr, bollinger_bands
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy


class AHPremiumStrategy(DaytradeStrategy):
    name = "hk_ah_premium"
    description = "AH 溢价收敛 — H 股极度折价时买入，等待收敛"

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__(params)
        p = {**self.default_params(), **(params or {})}
        self.lookback: int = p["lookback"]
        self.rsi_period: int = p["rsi_period"]
        self.rsi_buy: float = p["rsi_buy"]
        self.rsi_sell: float = p["rsi_sell"]
        self.bb_period: int = p["bb_period"]
        self.bb_std: float = p["bb_std"]
        self.trend_ma: int = p["trend_ma"]
        self.atr_period: int = p["atr_period"]
        self.atr_sl_mult: float = p["atr_sl_mult"]
        self.target_pct: float = p["target_pct"]
        self.pullback_pct: float = p["pullback_pct"]

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        return {
            "lookback": 60,           # measure discount over this period
            "rsi_period": 14,
            "rsi_buy": 30.0,          # RSI oversold = H-share beaten down
            "rsi_sell": 70.0,         # RSI overbought = take profit
            "bb_period": 20,
            "bb_std": 2.0,
            "trend_ma": 120,          # ~6 months: long-term support
            "atr_period": 14,
            "atr_sl_mult": 2.5,
            "target_pct": 8.0,        # target % recovery
            "pullback_pct": 10.0,     # require X% pullback from recent high
        }

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        return {
            "rsi_buy": (20, 35, 5),
            "rsi_sell": (65, 80, 5),
            "bb_std": (1.5, 3.0, 0.25),
            "trend_ma": (60, 200, 20),
            "atr_sl_mult": (2.0, 4.0, 0.5),
            "target_pct": (5.0, 15.0, 2.5),
            "pullback_pct": (5.0, 20.0, 2.5),
        }

    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        min_len = max(self.trend_ma + 1, self.bb_period + 1, self.rsi_period + 2,
                      self.atr_period + 1, self.lookback + 1)
        if len(history) < min_len:
            return None

        if self._in_position:
            return self._check_exit(candle, history)

        closes = [c.close for c in history]
        rsi_vals = rsi(closes, self.rsi_period)
        trend = sma(closes, self.trend_ma)
        upper, mid, lower = bollinger_bands(closes, self.bb_period, self.bb_std)
        atr_vals = atr(history, self.atr_period)

        cur_rsi = rsi_vals[-1]
        prev_rsi = rsi_vals[-2]
        cur_trend = trend[-1]
        cur_atr = atr_vals[-1]

        if any(v != v for v in [cur_rsi, cur_trend, cur_atr]):
            return None

        # Measure pullback from recent high
        recent_high = max(c.high for c in history[-self.lookback:])
        pullback = (recent_high - candle.close) / recent_high * 100

        # Buy conditions:
        # 1. Price pulled back significantly (H-share discount widened)
        # 2. RSI oversold and turning up (selling exhaustion)
        # 3. Price at or below Bollinger lower band (statistically extreme)
        # 4. Price not too far below trend MA (not in freefall)
        max_below_trend = 15.0  # allow up to 15% below MA

        if (pullback >= self.pullback_pct
                and cur_rsi <= self.rsi_buy
                and cur_rsi > prev_rsi  # RSI turning up
                and candle.close <= lower[-1]
                and candle.close >= cur_trend * (1 - max_below_trend / 100)):

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
                reason=(f"AH溢价收敛买入 (回撤={pullback:.1f}%, RSI={cur_rsi:.0f}, "
                        f"触及BB下轨)"),
                confidence=min(65 + pullback, 90),
                stop_loss=sl, take_profit=tp,
                meta={
                    "pullback_pct": round(pullback, 1),
                    "rsi": round(cur_rsi, 1),
                    "recent_high": recent_high,
                    "trend_ma": round(cur_trend, 2),
                    "bb_lower": round(lower[-1], 2),
                },
            )

        return None

    def _check_exit(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        # Stop loss
        if candle.low <= self._stop_loss:
            self._in_position = False
            return Signal(timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                          price=self._stop_loss, reason="止损")

        # Take profit
        if candle.high >= self._take_profit:
            self._in_position = False
            return Signal(timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                          price=self._take_profit, reason=f"止盈 (+{self.target_pct}%)")

        # RSI overbought exit (premium converged)
        closes = [c.close for c in history]
        rsi_vals = rsi(closes, self.rsi_period)
        if rsi_vals[-1] == rsi_vals[-1] and rsi_vals[-1] >= self.rsi_sell:
            self._in_position = False
            return Signal(timestamp_ms=candle.timestamp_ms, side=Side.LONG,
                          price=candle.close,
                          reason=f"RSI 超买出场 ({rsi_vals[-1]:.0f})")

        return None
