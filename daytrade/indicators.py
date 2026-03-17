"""Technical indicators for intraday strategies."""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

from daytrade.models import Candle


def ema(values: List[float], period: int) -> List[float]:
    """Exponential Moving Average."""
    period = int(period)
    if not values or period < 1:
        return []
    result = [values[0]]
    k = 2.0 / (period + 1)
    for i in range(1, len(values)):
        result.append(values[i] * k + result[-1] * (1 - k))
    return result


def sma(values: List[float], period: int) -> List[float]:
    """Simple Moving Average — returns NaN for first (period-1) values."""
    period = int(period)
    result: List[float] = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(float("nan"))
        else:
            result.append(sum(values[i - period + 1: i + 1]) / period)
    return result


def rsi(closes: List[float], period: int = 14) -> List[float]:
    """Relative Strength Index (Wilder smoothing)."""
    period = int(period)
    if len(closes) < period + 1:
        return [float("nan")] * len(closes)

    result = [float("nan")] * period
    gains, losses = [], []

    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        result.append(100.0)
    else:
        rs = avg_gain / avg_loss
        result.append(100.0 - 100.0 / (1 + rs))

    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0)
        loss = max(-delta, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100.0 - 100.0 / (1 + rs))

    return result


def atr(candles: List[Candle], period: int = 14) -> List[float]:
    """Average True Range."""
    period = int(period)
    if len(candles) < 2:
        return [0.0] * len(candles)

    trs = [candles[0].high - candles[0].low]
    for i in range(1, len(candles)):
        c = candles[i]
        prev_close = candles[i - 1].close
        tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
        trs.append(tr)

    result: List[float] = []
    for i in range(len(trs)):
        if i < period - 1:
            result.append(float("nan"))
        elif i == period - 1:
            result.append(sum(trs[:period]) / period)
        else:
            result.append((result[-1] * (period - 1) + trs[i]) / period)
    return result


def vwap(candles: List[Candle]) -> List[float]:
    """Volume-Weighted Average Price (cumulative, resets daily).

    Groups candles by UTC day and resets accumulation at each boundary.
    """
    if not candles:
        return []

    result: List[float] = []
    cum_pv = 0.0
    cum_vol = 0.0
    current_day = -1

    for c in candles:
        day = c.timestamp_ms // 86_400_000
        if day != current_day:
            cum_pv = 0.0
            cum_vol = 0.0
            current_day = day

        typical = (c.high + c.low + c.close) / 3
        cum_pv += typical * c.volume
        cum_vol += c.volume
        result.append(cum_pv / cum_vol if cum_vol > 0 else c.close)

    return result


def bollinger_bands(
    closes: List[float], period: int = 20, num_std: float = 2.0
) -> Tuple[List[float], List[float], List[float]]:
    """Bollinger Bands — returns (upper, middle, lower)."""
    period = int(period)
    mid = sma(closes, period)
    upper, lower = [], []

    for i in range(len(closes)):
        if i < period - 1:
            upper.append(float("nan"))
            lower.append(float("nan"))
        else:
            window = closes[i - period + 1: i + 1]
            m = mid[i]
            std = math.sqrt(sum((x - m) ** 2 for x in window) / period)
            upper.append(m + num_std * std)
            lower.append(m - num_std * std)

    return upper, mid, lower


def macd(
    closes: List[float], fast: int = 12, slow: int = 26, signal_period: int = 9
) -> Tuple[List[float], List[float], List[float]]:
    """MACD — returns (macd_line, signal_line, histogram)."""
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = ema(macd_line, signal_period)
    histogram = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, histogram
