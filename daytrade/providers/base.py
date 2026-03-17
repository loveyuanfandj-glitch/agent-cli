"""Abstract data provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from daytrade.models import Candle


class DataProvider(ABC):
    """Base class for all market data providers."""

    name: str = "base"

    @abstractmethod
    def fetch_candles(
        self,
        symbol: str,
        interval: str = "15m",
        lookback_days: int = 7,
    ) -> List[Candle]:
        """Fetch OHLCV candle data for a symbol."""
        ...

    @abstractmethod
    def list_instruments(self) -> List[Dict[str, str]]:
        """Return available instruments as [{symbol, name, category}, ...]."""
        ...
