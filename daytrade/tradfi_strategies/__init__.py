"""TradFi strategy registry — long-term strategies for commodities, stocks, and ETFs."""
from __future__ import annotations

from typing import Dict, Type

from daytrade.strategies.base import DaytradeStrategy

from daytrade.tradfi_strategies.commodity_trend import CommodityTrendStrategy
from daytrade.tradfi_strategies.commodity_reversion import CommodityReversionStrategy
from daytrade.tradfi_strategies.stock_gap_fill import GapFillStrategy
from daytrade.tradfi_strategies.stock_vwap_scalp import VWAPScalpStrategy
from daytrade.tradfi_strategies.etf_orb import ETFOpeningRangeStrategy
from daytrade.tradfi_strategies.etf_mean_reversion import ETFMeanReversionStrategy


COMMODITY_STRATEGIES: Dict[str, Type[DaytradeStrategy]] = {
    "commodity_trend": CommodityTrendStrategy,
    "commodity_reversion": CommodityReversionStrategy,
}

STOCK_STRATEGIES: Dict[str, Type[DaytradeStrategy]] = {
    "stock_momentum": GapFillStrategy,
    "stock_ma_pullback": VWAPScalpStrategy,
}

ETF_STRATEGIES: Dict[str, Type[DaytradeStrategy]] = {
    "etf_dual_momentum": ETFOpeningRangeStrategy,
    "etf_smart_dca": ETFMeanReversionStrategy,
}

COMMODITY_DESCRIPTIONS: Dict[str, str] = {
    "commodity_trend": "商品趋势跟随 — MA 交叉 + ADX 过滤，宽幅追踪止损 (持有数周~数月)",
    "commodity_reversion": "商品抄底 — 上升趋势中深度回调 + RSI 超卖买入 (持有数周~数月)",
}

STOCK_DESCRIPTIONS: Dict[str, str] = {
    "stock_momentum": "个股动量突破 — 放量突破新高后持有，追踪止损保护 (持有数周~数月)",
    "stock_ma_pullback": "个股均线回踩 — 上升趋势回踩 MA20/50 时买入 (持有数天~数周)",
}

ETF_DESCRIPTIONS: Dict[str, str] = {
    "etf_dual_momentum": "ETF 双动量 — 绝对动量 + 趋势过滤，低频轮动 (持有数月)",
    "etf_smart_dca": "ETF 智能定投 — RSI 择时增强定投，低买高持 (持有数月~数年)",
}
