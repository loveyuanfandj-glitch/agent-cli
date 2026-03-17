"""TradFi strategy registry — separate strategies for commodities, stocks, and ETFs."""
from __future__ import annotations

from typing import Dict, List, Type

from daytrade.strategies.base import DaytradeStrategy

# Commodity strategies
from daytrade.tradfi_strategies.commodity_trend import CommodityTrendStrategy
from daytrade.tradfi_strategies.commodity_reversion import CommodityReversionStrategy

# Stock strategies
from daytrade.tradfi_strategies.stock_gap_fill import GapFillStrategy
from daytrade.tradfi_strategies.stock_vwap_scalp import VWAPScalpStrategy

# ETF strategies
from daytrade.tradfi_strategies.etf_orb import ETFOpeningRangeStrategy
from daytrade.tradfi_strategies.etf_mean_reversion import ETFMeanReversionStrategy


COMMODITY_STRATEGIES: Dict[str, Type[DaytradeStrategy]] = {
    "commodity_trend": CommodityTrendStrategy,
    "commodity_reversion": CommodityReversionStrategy,
}

STOCK_STRATEGIES: Dict[str, Type[DaytradeStrategy]] = {
    "stock_gap_fill": GapFillStrategy,
    "stock_vwap_scalp": VWAPScalpStrategy,
}

ETF_STRATEGIES: Dict[str, Type[DaytradeStrategy]] = {
    "etf_orb": ETFOpeningRangeStrategy,
    "etf_mean_reversion": ETFMeanReversionStrategy,
}

COMMODITY_DESCRIPTIONS: Dict[str, str] = {
    "commodity_trend": "商品趋势跟随 — EMA+ADX 识别趋势，ATR 追踪止损",
    "commodity_reversion": "商品均值回归 — 布林带极端 + RSI 背离入场",
}

STOCK_DESCRIPTIONS: Dict[str, str] = {
    "stock_gap_fill": "缺口回补 — 隔夜跳空后日内回补，胜率 60-70%",
    "stock_vwap_scalp": "VWAP 刮头皮 — 机构基准价附近反复做多/做空",
}

ETF_DESCRIPTIONS: Dict[str, str] = {
    "etf_orb": "ETF 开盘区间突破 — 前 30 分钟定区间，突破后跟随",
    "etf_mean_reversion": "ETF 日内回归 — RSI + 布林带超卖/超买反向交易",
}
