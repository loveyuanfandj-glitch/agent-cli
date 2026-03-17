"""Scheduled scanner — auto-scan on interval and push to Feishu.

Usage:
    python3 -m daytrade.scheduled_scan --market hk --interval-min 30
    hl daytrade autoscan --market hk --every 30
"""
from __future__ import annotations

import datetime
import logging
import time
from typing import Dict, List

from daytrade.models import Side
from daytrade.providers.yahoo import YahooFinanceProvider
from daytrade.notify_feishu import notify_buy_signal, notify_sell_signal, notify_scan_summary, send_feishu

log = logging.getLogger("daytrade.scheduled")

_yf = YahooFinanceProvider()

# ---------------------------------------------------------------------------
# Market configs
# ---------------------------------------------------------------------------
HK_SYMBOLS = [
    # ETFs
    ("2800.HK", "盈富基金"), ("3067.HK", "恒生科技 ETF"), ("2828.HK", "H股 ETF"),
    ("3033.HK", "南方恒科 ETF"), ("2822.HK", "南方 A50"),
    # Stocks
    ("0700.HK", "腾讯"), ("9988.HK", "阿里"), ("3690.HK", "美团"),
    ("1810.HK", "小米"), ("1211.HK", "比亚迪"), ("0981.HK", "中芯国际"),
    ("9868.HK", "小鹏"), ("9866.HK", "蔚来"), ("2015.HK", "理想"),
    ("1024.HK", "快手"), ("9618.HK", "京东"),
]

US_SYMBOLS = [
    # ETFs
    ("SPY", "S&P 500"), ("QQQ", "纳斯达克 100"), ("GLD", "黄金"),
    ("SLV", "白银"), ("USO", "原油"), ("TLT", "20年国债"),
    # Stocks
    ("NVDA", "NVIDIA"), ("TSLA", "Tesla"), ("AAPL", "Apple"),
    ("COIN", "Coinbase"), ("MSTR", "MicroStrategy"), ("MARA", "Marathon"),
    ("IBIT", "BTC ETF"),
]

CRYPTO_SYMBOLS = [
    ("BTC-PERP", "Bitcoin"), ("ETH-PERP", "Ethereum"),
]


def _get_strategies(market: str):
    """Return strategy dict based on market."""
    if market == "hk":
        from daytrade.tradfi_strategies import COMMODITY_STRATEGIES, STOCK_STRATEGIES, ETF_STRATEGIES, HK_STRATEGIES
        return {**HK_STRATEGIES, **COMMODITY_STRATEGIES, **STOCK_STRATEGIES, **ETF_STRATEGIES}
    if market == "us":
        from daytrade.tradfi_strategies import COMMODITY_STRATEGIES, STOCK_STRATEGIES, ETF_STRATEGIES
        return {**COMMODITY_STRATEGIES, **STOCK_STRATEGIES, **ETF_STRATEGIES}
    else:
        from daytrade.strategies import STRATEGY_REGISTRY
        return STRATEGY_REGISTRY


def _get_symbols(market: str) -> List[tuple]:
    if market == "hk":
        return HK_SYMBOLS
    elif market == "us":
        return US_SYMBOLS
    else:
        return CRYPTO_SYMBOLS


def _get_provider(market: str):
    if market == "crypto":
        from daytrade.providers.hyperliquid import HyperliquidProvider
        return HyperliquidProvider(testnet=False)
    return _yf


def run_single_scan(
    market: str = "hk",
    candle_interval: str = "1d",
    lookback_days: int = 365,
    webhook_url: str = "",
) -> Dict:
    """Run one full scan and push results to Feishu. Returns summary dict."""
    symbols = _get_symbols(market)
    strategies = _get_strategies(market)
    provider = _get_provider(market)
    market_name = {"hk": "港股", "us": "美股", "crypto": "加密"}.get(market, market)

    now = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] 开始扫描 {market_name} ({len(symbols)} 品种 x {len(strategies)} 策略)...")

    buy_signals = []
    sell_signals = []
    errors = 0
    candle_cache: Dict = {}

    for sym, name in symbols:
        # Fetch candles (cached per symbol)
        if sym not in candle_cache:
            try:
                candle_cache[sym] = provider.fetch_candles(sym, candle_interval, lookback_days)
            except Exception as e:
                log.warning("Fetch failed %s: %s", sym, e)
                candle_cache[sym] = None
                errors += 1
                continue

        candles = candle_cache[sym]
        if not candles:
            errors += 1
            continue

        # Run each strategy
        for sname, scls in strategies.items():
            try:
                strat = scls()
                strat.reset()
                signal = None
                for idx, c in enumerate(candles):
                    sig = strat.on_candle(c, candles[:idx + 1])
                    if sig is not None and idx == len(candles) - 1:
                        signal = sig

                if signal:
                    entry = {
                        "symbol": sym, "name": name, "strategy": sname,
                        "signal": signal, "price": candles[-1].close,
                    }
                    if signal.side == Side.LONG:
                        buy_signals.append(entry)
                    else:
                        sell_signals.append(entry)
            except Exception as e:
                log.debug("Strategy %s failed on %s: %s", sname, sym, e)

    now = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] 扫描完成: 🟢 {len(buy_signals)} 买入  🔴 {len(sell_signals)} 卖出  ❌ {errors} 错误")

    # Push to Feishu
    if webhook_url and (buy_signals or sell_signals):
        for r in buy_signals:
            notify_buy_signal(r["symbol"], r["name"], r["signal"], r["price"], r["strategy"], webhook_url)
        for r in sell_signals:
            notify_sell_signal(r["symbol"], r["name"], r["signal"], r["price"], r["strategy"], webhook_url)
        notify_scan_summary(buy_signals, sell_signals, market_name, webhook_url)
        print(f"[{now}] 已推送到飞书")
    elif not buy_signals and not sell_signals:
        # Optional: notify no signal
        if webhook_url:
            send_feishu(
                f"📊 {market_name}定时扫描 — 无信号",
                [[{"tag": "text", "text": f"扫描时间: {now}  |  全部 {len(symbols)} 品种无买卖信号，继续观望。"}]],
                webhook_url,
            )

    # Print buy signals to terminal
    for r in buy_signals:
        sig = r["signal"]
        sl_str = f"  止损:{sig.stop_loss:.2f}" if sig.stop_loss else ""
        tp_str = f"  目标:{sig.take_profit:.2f}" if sig.take_profit else ""
        print(f"  🟢 {r['symbol']} {r['name']} @ {sig.price:.2f}  [{r['strategy']}]{sl_str}{tp_str}")
    for r in sell_signals:
        sig = r["signal"]
        print(f"  🔴 {r['symbol']} {r['name']} @ {sig.price:.2f}  [{r['strategy']}] {sig.reason}")

    return {
        "buy": len(buy_signals), "sell": len(sell_signals), "errors": errors,
        "buy_signals": buy_signals, "sell_signals": sell_signals,
    }


# ---------------------------------------------------------------------------
# Trading hours (UTC)
# ---------------------------------------------------------------------------
MARKET_HOURS = {
    "hk": {
        # HK: 09:30-16:00 HKT = 01:30-08:00 UTC
        "sessions": [(1, 30, 4, 0), (5, 0, 8, 0)],  # morning + afternoon
        "tz_name": "HKT (UTC+8)",
        "local_hours": "09:30-12:00, 13:00-16:00",
    },
    "us": {
        # US: 09:30-16:00 ET = 14:30-21:00 UTC (winter), 13:30-20:00 UTC (summer)
        "sessions": [(13, 30, 21, 0)],  # covers both DST variants
        "tz_name": "ET (UTC-4/-5)",
        "local_hours": "09:30-16:00",
    },
    "crypto": {
        # 24/7
        "sessions": [(0, 0, 23, 59)],
        "tz_name": "UTC (24/7)",
        "local_hours": "全天",
    },
}


def _is_market_open(market: str) -> bool:
    """Check if market is currently in trading hours (UTC)."""
    if market == "crypto":
        return True

    now = datetime.datetime.utcnow()
    hours = MARKET_HOURS.get(market, {}).get("sessions", [])

    for start_h, start_m, end_h, end_m in hours:
        start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
        if start <= now <= end:
            return True

    return False


def _next_open_time(market: str) -> str:
    """Return next market open time as a human-readable string."""
    now = datetime.datetime.utcnow()
    hours = MARKET_HOURS.get(market, {}).get("sessions", [])
    local_hours = MARKET_HOURS.get(market, {}).get("local_hours", "")
    tz_name = MARKET_HOURS.get(market, {}).get("tz_name", "")

    for start_h, start_m, _, _ in hours:
        open_time = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        if now < open_time:
            delta = open_time - now
            mins = int(delta.total_seconds() / 60)
            return f"{mins} 分钟后开盘 ({local_hours} {tz_name})"

    # Next day
    tomorrow_first = hours[0] if hours else (0, 0, 0, 0)
    open_time = (now + datetime.timedelta(days=1)).replace(
        hour=tomorrow_first[0], minute=tomorrow_first[1], second=0, microsecond=0,
    )
    # Skip weekends for HK and US
    if market in ("hk", "us"):
        while open_time.weekday() >= 5:  # Saturday=5, Sunday=6
            open_time += datetime.timedelta(days=1)

    delta = open_time - now
    hours_left = delta.total_seconds() / 3600
    if hours_left < 24:
        return f"{hours_left:.1f} 小时后开盘 ({local_hours} {tz_name})"
    else:
        return f"{open_time.strftime('%Y-%m-%d %H:%M')} UTC 开盘 ({local_hours} {tz_name})"


def _is_weekend(market: str) -> bool:
    """Check if today is a weekend (non-trading day) for the market."""
    if market == "crypto":
        return False
    return datetime.datetime.utcnow().weekday() >= 5


def run_scheduled(
    market: str = "hk",
    interval_min: int = 30,
    candle_interval: str = "1d",
    lookback_days: int = 365,
    webhook_url: str = "",
    max_runs: int = 0,
    trading_hours_only: bool = False,
):
    """Run scan on a schedule.

    If trading_hours_only=True, only scans during market open hours,
    sleeps during off-hours and weekends.
    """
    market_name = {"hk": "港股", "us": "美股", "crypto": "加密"}.get(market, market)
    symbols = _get_symbols(market)
    strategies = _get_strategies(market)
    mh = MARKET_HOURS.get(market, {})

    print(f"📡 定时扫描启动")
    print(f"   市场: {market_name} ({len(symbols)} 品种)")
    print(f"   策略: {len(strategies)} 个")
    print(f"   周期: {candle_interval} | 回溯: {lookback_days} 天")
    print(f"   扫描间隔: {interval_min} 分钟")
    print(f"   交易时段: {mh.get('local_hours', '全天')} {mh.get('tz_name', '')}")
    print(f"   仅开盘时间: {'✓' if trading_hours_only else '✗ (全天运行)'}")
    print(f"   飞书通知: {'✓ 已启用' if webhook_url else '✗ 未配置'}")
    print(f"   按 Ctrl+C 停止")
    print()

    # Notify start
    if webhook_url:
        mode = "开盘时段" if trading_hours_only else "全天"
        send_feishu(
            f"📡 {market_name}定时扫描已启动",
            [
                [{"tag": "text", "text": f"品种: {len(symbols)} 个  |  策略: {len(strategies)} 个"}],
                [{"tag": "text", "text": f"扫描间隔: {interval_min} 分钟  |  模式: {mode}"}],
                [{"tag": "text", "text": f"交易时段: {mh.get('local_hours', '全天')} {mh.get('tz_name', '')}"}],
            ],
            webhook_url,
        )

    run_count = 0
    notified_closed = False

    while True:
        run_count += 1
        if max_runs and run_count > max_runs:
            print("达到最大运行次数，停止。")
            break

        # Check trading hours
        if trading_hours_only:
            if _is_weekend(market):
                if not notified_closed:
                    next_open = _next_open_time(market)
                    print(f"  📅 周末休市，{next_open}")
                    notified_closed = True
                try:
                    time.sleep(300)  # check every 5 min on weekends
                except KeyboardInterrupt:
                    print("\n扫描已停止。")
                    break
                continue

            if not _is_market_open(market):
                if not notified_closed:
                    next_open = _next_open_time(market)
                    now_str = datetime.datetime.utcnow().strftime("%H:%M:%S")
                    print(f"  [{now_str}] 💤 未开盘，{next_open}")
                    notified_closed = True
                try:
                    time.sleep(60)  # check every 1 min during off-hours
                except KeyboardInterrupt:
                    print("\n扫描已停止。")
                    break
                continue
            else:
                if notified_closed:
                    now_str = datetime.datetime.utcnow().strftime("%H:%M:%S")
                    print(f"  [{now_str}] 🔔 开盘！开始扫描")
                    if webhook_url:
                        send_feishu(
                            f"🔔 {market_name}已开盘",
                            [[{"tag": "text", "text": "定时扫描开始运行"}]],
                            webhook_url,
                        )
                    notified_closed = False

        run_single_scan(market, candle_interval, lookback_days, webhook_url)

        if max_runs and run_count >= max_runs:
            break

        now_str = datetime.datetime.utcnow().strftime("%H:%M:%S")
        print(f"  [{now_str}] 下次扫描: {interval_min} 分钟后")
        print()
        try:
            time.sleep(interval_min * 60)
        except KeyboardInterrupt:
            print("\n扫描已停止。")
            break


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Scheduled market scanner")
    parser.add_argument("--market", default="hk", choices=["hk", "us", "crypto"])
    parser.add_argument("--interval-min", type=int, default=30)
    parser.add_argument("--candle-interval", default="1d")
    parser.add_argument("--lookback", type=int, default=365)
    parser.add_argument("--webhook", default="")
    parser.add_argument("--max-runs", type=int, default=0)
    parser.add_argument("--trading-hours", action="store_true", help="Only scan during market hours")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    run_scheduled(
        market=args.market,
        interval_min=args.interval_min,
        candle_interval=args.candle_interval,
        lookback_days=args.lookback,
        webhook_url=args.webhook,
        max_runs=args.max_runs,
        trading_hours_only=args.trading_hours,
    )
