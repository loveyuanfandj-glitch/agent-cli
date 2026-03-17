"""Data models for the daytrade module."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class Candle:
    """Single OHLCV candle."""
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @staticmethod
    def from_hl(raw: dict) -> "Candle":
        """Parse from Hyperliquid candle format."""
        return Candle(
            timestamp_ms=int(raw.get("t", raw.get("T", 0))),
            open=float(raw.get("o", raw.get("O", 0))),
            high=float(raw.get("h", raw.get("H", 0))),
            low=float(raw.get("l", raw.get("L", 0))),
            close=float(raw.get("c", raw.get("C", 0))),
            volume=float(raw.get("v", raw.get("V", 0))),
        )


@dataclass
class Signal:
    """A trading signal produced by a strategy."""
    timestamp_ms: int
    side: Side
    price: float
    reason: str
    confidence: float = 0.0  # 0-100
    stop_loss: float = 0.0
    take_profit: float = 0.0
    meta: dict = field(default_factory=dict)


@dataclass
class Trade:
    """A completed round-trip trade."""
    instrument: str
    side: Side
    entry_time: int
    entry_price: float
    exit_time: int
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float
    fees: float
    reason_entry: str
    reason_exit: str
    duration_min: float = 0.0

    @property
    def is_win(self) -> bool:
        return self.pnl > 0


@dataclass
class BacktestResult:
    """Aggregated backtest metrics."""
    instrument: str
    strategy: str
    start_time: int
    end_time: int
    candles_count: int
    trades: List[Trade]

    # Computed metrics
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    net_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_duration_min: float = 0.0
    sharpe_ratio: float = 0.0
    equity_curve: List[float] = field(default_factory=list)

    def compute(self):
        """Compute all metrics from the trade list."""
        self.total_trades = len(self.trades)
        if not self.trades:
            return

        self.wins = sum(1 for t in self.trades if t.is_win)
        self.losses = self.total_trades - self.wins
        self.win_rate = (self.wins / self.total_trades) * 100

        self.gross_profit = sum(t.pnl for t in self.trades if t.pnl > 0)
        self.gross_loss = abs(sum(t.pnl for t in self.trades if t.pnl <= 0))
        self.net_pnl = self.gross_profit - self.gross_loss
        self.profit_factor = (
            self.gross_profit / self.gross_loss if self.gross_loss > 0 else float("inf")
        )

        wins_list = [t.pnl for t in self.trades if t.is_win]
        loss_list = [t.pnl for t in self.trades if not t.is_win]
        self.avg_win = sum(wins_list) / len(wins_list) if wins_list else 0
        self.avg_loss = sum(loss_list) / len(loss_list) if loss_list else 0

        durations = [(t.exit_time - t.entry_time) / 60_000 for t in self.trades]
        for t in self.trades:
            t.duration_min = (t.exit_time - t.entry_time) / 60_000
        self.avg_duration_min = sum(durations) / len(durations) if durations else 0

        # Equity curve and drawdown
        equity = [0.0]
        for t in self.trades:
            equity.append(equity[-1] + t.pnl)
        self.equity_curve = equity

        peak = equity[0]
        max_dd = 0.0
        for val in equity:
            if val > peak:
                peak = val
            dd = peak - val
            if dd > max_dd:
                max_dd = dd
        self.max_drawdown_pct = (max_dd / max(peak, 1.0)) * 100 if peak > 0 else 0.0

        # Sharpe (simplified: daily returns approximation)
        returns = [t.pnl_pct for t in self.trades]
        if len(returns) > 1:
            import math
            mean_r = sum(returns) / len(returns)
            var_r = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
            std_r = math.sqrt(var_r) if var_r > 0 else 1e-9
            self.sharpe_ratio = (mean_r / std_r) * math.sqrt(252)
        return self
