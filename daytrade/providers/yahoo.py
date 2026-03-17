"""Yahoo Finance data provider — stocks, ETFs, forex, commodities."""
from __future__ import annotations

import logging
from typing import Dict, List

from daytrade.models import Candle
from daytrade.providers.base import DataProvider

log = logging.getLogger("daytrade.providers.yahoo")

# TradFi instruments
TRADFI_INSTRUMENTS = [
    # US Equity ETFs
    {"symbol": "SPY", "name": "S&P 500 ETF", "category": "美股指数"},
    {"symbol": "QQQ", "name": "纳斯达克 100 ETF", "category": "美股指数"},
    {"symbol": "IWM", "name": "罗素 2000 ETF (小盘)", "category": "美股指数"},
    {"symbol": "DIA", "name": "道琼斯 ETF", "category": "美股指数"},
    # Sector ETFs
    {"symbol": "XLF", "name": "金融板块 ETF", "category": "板块"},
    {"symbol": "XLK", "name": "科技板块 ETF", "category": "板块"},
    {"symbol": "XLE", "name": "能源板块 ETF", "category": "板块"},
    {"symbol": "XLV", "name": "医疗板块 ETF", "category": "板块"},
    # Commodities
    {"symbol": "GLD", "name": "黄金 ETF (SPDR Gold)", "category": "商品"},
    {"symbol": "SLV", "name": "白银 ETF (iShares Silver)", "category": "商品"},
    {"symbol": "USO", "name": "原油 ETF (WTI 原油)", "category": "商品"},
    {"symbol": "UNG", "name": "天然气 ETF", "category": "商品"},
    {"symbol": "GDX", "name": "金矿股 ETF", "category": "商品"},
    # Bonds
    {"symbol": "TLT", "name": "20年+ 美国国债 ETF", "category": "债券"},
    {"symbol": "SHY", "name": "1-3年 美国国债 ETF", "category": "债券"},
    {"symbol": "HYG", "name": "高收益公司债 ETF", "category": "债券"},
    # Volatility
    {"symbol": "UVXY", "name": "波动率 1.5x ETF", "category": "波动率"},
    {"symbol": "VXX", "name": "VIX 短期期货 ETF", "category": "波动率"},
    # Forex (via CurrencyShares ETFs and futures)
    {"symbol": "FXE", "name": "欧元 ETF", "category": "外汇"},
    {"symbol": "FXY", "name": "日元 ETF", "category": "外汇"},
    {"symbol": "FXB", "name": "英镑 ETF", "category": "外汇"},
    {"symbol": "UUP", "name": "美元指数 ETF", "category": "外汇"},
    # Mega caps
    {"symbol": "AAPL", "name": "Apple", "category": "个股"},
    {"symbol": "MSFT", "name": "Microsoft", "category": "个股"},
    {"symbol": "NVDA", "name": "NVIDIA", "category": "个股"},
    {"symbol": "TSLA", "name": "Tesla", "category": "个股"},
    {"symbol": "AMZN", "name": "Amazon", "category": "个股"},
    {"symbol": "META", "name": "Meta (Facebook)", "category": "个股"},
    {"symbol": "GOOG", "name": "Alphabet (Google)", "category": "个股"},
    # Crypto-related stocks
    {"symbol": "COIN", "name": "Coinbase", "category": "加密个股"},
    {"symbol": "MSTR", "name": "MicroStrategy (BTC 持仓)", "category": "加密个股"},
    {"symbol": "MARA", "name": "Marathon Digital (BTC 矿企)", "category": "加密个股"},
    {"symbol": "RIOT", "name": "Riot Platforms (BTC 矿企)", "category": "加密个股"},
    {"symbol": "CLSK", "name": "CleanSpark (BTC 矿企)", "category": "加密个股"},
    {"symbol": "HUT", "name": "Hut 8 Mining", "category": "加密个股"},
    {"symbol": "BITF", "name": "Bitfarms (矿企)", "category": "加密个股"},
    {"symbol": "HOOD", "name": "Robinhood", "category": "加密个股"},
    {"symbol": "SQ", "name": "Block (Square)", "category": "加密个股"},
    {"symbol": "IBIT", "name": "iShares Bitcoin ETF", "category": "加密个股"},
    {"symbol": "FBTC", "name": "Fidelity Bitcoin ETF", "category": "加密个股"},
]

# yfinance interval mapping
# yfinance valid intervals: 1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo
_INTERVAL_MAP = {
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "60m",
    "4h": "60m",  # yfinance doesn't have 4h; will resample
    "1d": "1d",
    "1wk": "1wk",
    "1mo": "1mo",
}

_MAX_INTRADAY_DAYS = {
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "60m": 730,
    "1d": 10000,
    "1wk": 10000,
    "1mo": 10000,
}


class YahooFinanceProvider(DataProvider):
    name = "yahoo"

    def fetch_candles(
        self,
        symbol: str,
        interval: str = "15m",
        lookback_days: int = 7,
    ) -> List[Candle]:
        try:
            import yfinance as yf
        except ImportError:
            log.error("yfinance not installed. Run: pip install yfinance")
            return []

        yf_interval = _INTERVAL_MAP.get(interval, "15m")
        max_days = _MAX_INTRADAY_DAYS.get(yf_interval, 60)
        days = min(lookback_days, max_days)

        # Build period string
        period = f"{days}d"

        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=yf_interval)

            if df.empty:
                log.warning("No data from Yahoo Finance for %s", symbol)
                return []

            candles = []
            for idx, row in df.iterrows():
                ts_ms = int(idx.timestamp() * 1000)
                candles.append(Candle(
                    timestamp_ms=ts_ms,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row["Volume"]),
                ))

            # Resample 4h from 1h if needed
            if interval == "4h" and yf_interval == "60m" and candles:
                candles = _resample_candles(candles, 4)

            candles.sort(key=lambda c: c.timestamp_ms)
            log.info("Fetched %d candles for %s from Yahoo Finance", len(candles), symbol)
            return candles

        except Exception as e:
            log.warning("Yahoo Finance fetch failed for %s: %s", symbol, e)
            return []

    def list_instruments(self) -> List[Dict[str, str]]:
        return TRADFI_INSTRUMENTS


def _resample_candles(candles: List[Candle], factor: int) -> List[Candle]:
    """Resample candles by grouping N candles into 1."""
    result = []
    for i in range(0, len(candles), factor):
        group = candles[i: i + factor]
        if not group:
            continue
        result.append(Candle(
            timestamp_ms=group[0].timestamp_ms,
            open=group[0].open,
            high=max(c.high for c in group),
            low=min(c.low for c in group),
            close=group[-1].close,
            volume=sum(c.volume for c in group),
        ))
    return result
