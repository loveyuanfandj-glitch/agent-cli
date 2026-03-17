"""Hyperliquid data provider — crypto perps and YEX markets."""
from __future__ import annotations

import logging
import time
from typing import Dict, List

from daytrade.models import Candle
from daytrade.providers.base import DataProvider

log = logging.getLogger("daytrade.providers.hl")


# Crypto instruments
HL_INSTRUMENTS = [
    {"symbol": "BTC-PERP", "name": "Bitcoin", "category": "Crypto"},
    {"symbol": "ETH-PERP", "name": "Ethereum", "category": "Crypto"},
    {"symbol": "PAXG-PERP", "name": "PAX Gold (黄金锚定)", "category": "Crypto"},
    {"symbol": "SOL-PERP", "name": "Solana", "category": "Crypto"},
    {"symbol": "XRP-PERP", "name": "XRP", "category": "Crypto"},
    {"symbol": "BNB-PERP", "name": "BNB", "category": "Crypto"},
    {"symbol": "DOGE-PERP", "name": "Dogecoin", "category": "Crypto"},
    {"symbol": "LINK-PERP", "name": "Chainlink", "category": "Crypto"},
    {"symbol": "AVAX-PERP", "name": "Avalanche", "category": "Crypto"},
    {"symbol": "VXX-USDYP", "name": "VXX 波动率 (YEX)", "category": "YEX"},
    {"symbol": "US3M-USDYP", "name": "US 3M 国债 (YEX)", "category": "YEX"},
    {"symbol": "BTCSWP-USDYP", "name": "BTC 利率互换 (YEX)", "category": "YEX"},
]


def _to_hl_coin(instrument: str) -> str:
    """Map instrument name to HL coin."""
    try:
        from cli.strategy_registry import YEX_MARKETS
        yex = YEX_MARKETS.get(instrument)
        if yex:
            return yex["hl_coin"]
    except ImportError:
        pass
    return instrument.replace("-PERP", "").replace("-perp", "")


class HyperliquidProvider(DataProvider):
    name = "hyperliquid"

    def __init__(self, testnet: bool = False):
        self.testnet = testnet

    def fetch_candles(
        self,
        symbol: str,
        interval: str = "15m",
        lookback_days: int = 7,
    ) -> List[Candle]:
        coin = _to_hl_coin(symbol)
        lookback_ms = lookback_days * 86_400_000

        try:
            from hyperliquid.info import Info
            from hyperliquid.utils import constants

            base_url = constants.TESTNET_API_URL if self.testnet else constants.MAINNET_API_URL
            info = Info(base_url, skip_ws=True)
            end = int(time.time() * 1000)
            start = end - lookback_ms
            raw = info.candles_snapshot(coin, interval, start, end)

            candles = []
            for r in raw:
                try:
                    candles.append(Candle.from_hl(r))
                except Exception:
                    continue
            candles.sort(key=lambda c: c.timestamp_ms)
            return candles

        except Exception as e:
            log.warning("HL candle fetch failed for %s: %s", symbol, e)
            return []

    def list_instruments(self) -> List[Dict[str, str]]:
        return HL_INSTRUMENTS
