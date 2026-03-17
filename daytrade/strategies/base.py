"""Base class for intraday strategies."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any

from daytrade.models import Candle, Signal


class DaytradeStrategy(ABC):
    """Base class for all daytrade strategies.

    Strategies process candles one-by-one and emit Signal objects.
    They maintain internal state (indicators, positions) and handle
    both entry and exit logic.
    """

    name: str = "base"
    description: str = ""

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        self.params = params or {}
        self._in_position = False
        self._position_side: Optional[str] = None
        self._entry_price: float = 0.0
        self._entry_time: int = 0
        self._stop_loss: float = 0.0
        self._take_profit: float = 0.0

    @abstractmethod
    def on_candle(self, candle: Candle, history: List[Candle]) -> Optional[Signal]:
        """Process a new candle and optionally return a signal.

        Args:
            candle: The latest candle.
            history: All candles up to and including the current one.

        Returns:
            A Signal if the strategy wants to enter/exit, or None.
        """
        ...

    def reset(self):
        """Reset internal state for a new backtest run."""
        self._in_position = False
        self._position_side = None
        self._entry_price = 0.0
        self._entry_time = 0
        self._stop_loss = 0.0
        self._take_profit = 0.0

    @classmethod
    def default_params(cls) -> Dict[str, Any]:
        """Return default parameter dict for this strategy."""
        return {}

    @classmethod
    def param_ranges(cls) -> Dict[str, tuple]:
        """Return (min, max, step) for each tunable parameter."""
        return {}
