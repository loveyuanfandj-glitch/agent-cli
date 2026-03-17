"""Backtest engine — replays candle data through daytrade strategies."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from daytrade.models import BacktestResult, Candle, Signal, Side, Trade
from daytrade.strategies.base import DaytradeStrategy

log = logging.getLogger("daytrade.backtest")

# Fee rate: 3 bps taker each way (entry + exit)
DEFAULT_FEE_BPS = 3.0

# Supported instruments
INSTRUMENTS = [
    "BTC-PERP",
    "ETH-PERP",
    "PAXG-PERP",     # 黄金 (PAX Gold, 锚定实物金价)
    "SOL-PERP",
    "XRP-PERP",
    "BNB-PERP",
    "DOGE-PERP",
    "LINK-PERP",
    "AVAX-PERP",
    "VXX-USDYP",
    "US3M-USDYP",
    "BTCSWP-USDYP",
]


def fetch_candles_hl(
    instrument: str,
    interval: str = "15m",
    lookback_days: int = 7,
    testnet: bool = True,
) -> List[Candle]:
    """Fetch candle data from Hyperliquid API.

    Uses the Info API directly — no private key needed (read-only public data).
    """
    from cli.strategy_registry import YEX_MARKETS

    lookback_ms = lookback_days * 86_400_000

    # Map instrument to HL coin
    yex = YEX_MARKETS.get(instrument)
    if yex:
        coin = yex["hl_coin"]
    else:
        coin = instrument.replace("-PERP", "").replace("-perp", "")

    raw_candles = []
    try:
        from hyperliquid.info import Info
        from hyperliquid.utils import constants

        base_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
        info = Info(base_url, skip_ws=True)
        end = int(time.time() * 1000)
        start = end - lookback_ms
        raw_candles = info.candles_snapshot(coin, interval, start, end)
        log.info("Fetched %d candles for %s from %s",
                 len(raw_candles), coin, "testnet" if testnet else "mainnet")
    except Exception as e:
        log.warning("HL candle fetch failed: %s — falling back to mock", e)
        from parent.hl_proxy import MockHLProxy
        mock = MockHLProxy()
        raw_candles = mock.get_candles(coin, interval, lookback_ms)

    candles = []
    for raw in raw_candles:
        try:
            candles.append(Candle.from_hl(raw))
        except Exception:
            continue

    candles.sort(key=lambda c: c.timestamp_ms)
    return candles


def load_candles_csv(path: str) -> List[Candle]:
    """Load candles from a CSV file (timestamp_ms,open,high,low,close,volume)."""
    candles = []
    with open(path) as f:
        header = f.readline()  # skip header
        for line in f:
            parts = line.strip().split(",")
            if len(parts) >= 6:
                candles.append(Candle(
                    timestamp_ms=int(parts[0]),
                    open=float(parts[1]),
                    high=float(parts[2]),
                    low=float(parts[3]),
                    close=float(parts[4]),
                    volume=float(parts[5]),
                ))
    return candles


def save_candles_csv(candles: List[Candle], path: str):
    """Save candles to CSV for offline backtesting."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write("timestamp_ms,open,high,low,close,volume\n")
        for c in candles:
            f.write(f"{c.timestamp_ms},{c.open},{c.high},{c.low},{c.close},{c.volume}\n")


def run_backtest(
    strategy: DaytradeStrategy,
    candles: List[Candle],
    instrument: str = "BTC-PERP",
    size: float = 1.0,
    fee_bps: float = DEFAULT_FEE_BPS,
) -> BacktestResult:
    """Run a backtest of a strategy on candle data.

    Returns BacktestResult with all trades and computed metrics.
    """
    strategy.reset()
    trades: List[Trade] = []
    pending_entry: Optional[Signal] = None

    for i, candle in enumerate(candles):
        history = candles[: i + 1]
        signal = strategy.on_candle(candle, history)

        if signal is None:
            continue

        if pending_entry is None:
            # This is an entry signal
            pending_entry = signal
        else:
            # This is an exit signal — close the trade
            entry = pending_entry
            exit_signal = signal

            if entry.side == Side.LONG:
                raw_pnl = (exit_signal.price - entry.price) * size
            else:
                raw_pnl = (entry.price - exit_signal.price) * size

            fee = (entry.price + exit_signal.price) * size * fee_bps / 10_000
            net_pnl = raw_pnl - fee
            pnl_pct = (net_pnl / (entry.price * size)) * 100

            trades.append(Trade(
                instrument=instrument,
                side=entry.side,
                entry_time=entry.timestamp_ms,
                entry_price=entry.price,
                exit_time=exit_signal.timestamp_ms,
                exit_price=exit_signal.price,
                size=size,
                pnl=round(net_pnl, 4),
                pnl_pct=round(pnl_pct, 4),
                fees=round(fee, 4),
                reason_entry=entry.reason,
                reason_exit=exit_signal.reason,
            ))
            pending_entry = None

    result = BacktestResult(
        instrument=instrument,
        strategy=strategy.name,
        start_time=candles[0].timestamp_ms if candles else 0,
        end_time=candles[-1].timestamp_ms if candles else 0,
        candles_count=len(candles),
        trades=trades,
    )
    result.compute()
    return result


def run_multi_backtest(
    strategy_class: type,
    candles: List[Candle],
    instrument: str,
    param_grid: Dict[str, List],
    size: float = 1.0,
) -> List[BacktestResult]:
    """Run backtest across a parameter grid, return sorted by net_pnl."""
    import itertools

    keys = list(param_grid.keys())
    values = list(param_grid.values())
    results = []

    for combo in itertools.product(*values):
        params = dict(zip(keys, combo))
        strat = strategy_class(params=params)
        result = run_backtest(strat, candles, instrument, size)
        result.strategy = f"{strat.name} ({params})"
        results.append(result)

    results.sort(key=lambda r: r.net_pnl, reverse=True)
    return results
