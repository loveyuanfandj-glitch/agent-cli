"""hl daytrade — low-frequency intraday timing tool."""
from __future__ import annotations

import logging
import sys

import typer

log = logging.getLogger("daytrade")

daytrade_app = typer.Typer(no_args_is_help=True)


@daytrade_app.command("ui")
def ui_cmd(
    port: int = typer.Option(8501, help="Streamlit server port"),
    host: str = typer.Option("localhost", help="Bind host"),
):
    """Launch the crypto daytrade GUI (Streamlit)."""
    import subprocess
    import os

    app_path = os.path.join(os.path.dirname(__file__), "..", "..", "daytrade", "app.py")
    app_path = os.path.abspath(app_path)

    typer.echo(f"Starting Nunchi Crypto Daytrade on http://{host}:{port}")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", app_path,
         "--server.port", str(port),
         "--server.address", host,
         "--theme.base", "dark"],
    )


@daytrade_app.command("tradfi")
def tradfi_cmd(
    port: int = typer.Option(8502, help="Streamlit server port"),
    host: str = typer.Option("localhost", help="Bind host"),
):
    """Launch the TradFi daytrade GUI (stocks, ETFs, commodities)."""
    import subprocess
    import os

    app_path = os.path.join(os.path.dirname(__file__), "..", "..", "daytrade", "tradfi_app.py")
    app_path = os.path.abspath(app_path)

    typer.echo(f"Starting Nunchi TradFi Daytrade on http://{host}:{port}")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", app_path,
         "--server.port", str(port),
         "--server.address", host,
         "--theme.base", "dark"],
    )


@daytrade_app.command("hk")
def hk_cmd(
    port: int = typer.Option(8503, help="Streamlit server port"),
    host: str = typer.Option("localhost", help="Bind host"),
):
    """Launch the HK market GUI (Hong Kong ETFs and stocks)."""
    import subprocess
    import os

    app_path = os.path.join(os.path.dirname(__file__), "..", "..", "daytrade", "hk_app.py")
    app_path = os.path.abspath(app_path)

    typer.echo(f"Starting Nunchi HK Market on http://{host}:{port}")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", app_path,
         "--server.port", str(port),
         "--server.address", host,
         "--theme.base", "dark"],
    )


@daytrade_app.command("backtest")
def backtest_cmd(
    instrument: str = typer.Option("BTC-PERP", "-i", help="Trading instrument"),
    strategy: str = typer.Option("ema_crossover", "-s", help="Strategy name"),
    interval: str = typer.Option("15m", help="Candle interval"),
    lookback: int = typer.Option(7, help="Lookback days"),
    size: float = typer.Option(1.0, help="Position size"),
    testnet: bool = typer.Option(False, help="Use testnet data"),
    csv: str = typer.Option("", help="Path to CSV candle file (optional)"),
    save_csv: str = typer.Option("", help="Save fetched candles to CSV"),
):
    """Run a CLI backtest without the GUI."""
    from daytrade.strategies import STRATEGY_REGISTRY, STRATEGY_DESCRIPTIONS
    from daytrade.backtest import fetch_candles_hl, load_candles_csv, save_candles_csv, run_backtest

    if strategy not in STRATEGY_REGISTRY:
        typer.echo(f"Unknown strategy: {strategy}")
        typer.echo(f"Available: {', '.join(STRATEGY_REGISTRY.keys())}")
        raise typer.Exit(1)

    # Load candles
    if csv:
        typer.echo(f"Loading candles from {csv}...")
        candles = load_candles_csv(csv)
    else:
        typer.echo(f"Fetching {instrument} {interval} candles ({lookback} days)...")
        candles = fetch_candles_hl(instrument, interval, lookback, testnet=testnet)

    if not candles:
        typer.echo("No candle data available.")
        raise typer.Exit(1)

    if save_csv:
        save_candles_csv(candles, save_csv)
        typer.echo(f"Saved {len(candles)} candles to {save_csv}")

    typer.echo(f"Loaded {len(candles)} candles")

    # Run backtest
    strat_cls = STRATEGY_REGISTRY[strategy]
    strat = strat_cls()
    result = run_backtest(strat, candles, instrument, size=size)

    # Print results
    typer.echo("")
    typer.echo(f"{'=' * 50}")
    typer.echo(f"  {strategy} | {instrument} | {interval}")
    typer.echo(f"{'=' * 50}")
    typer.echo(f"  总交易:    {result.total_trades}")
    typer.echo(f"  胜率:      {result.win_rate:.1f}%")
    typer.echo(f"  净盈亏:    ${result.net_pnl:.2f}")
    typer.echo(f"  盈亏比:    {result.profit_factor:.2f}")
    typer.echo(f"  最大回撤:  {result.max_drawdown_pct:.1f}%")
    typer.echo(f"  Sharpe:    {result.sharpe_ratio:.2f}")
    typer.echo(f"  平均盈利:  ${result.avg_win:.2f}")
    typer.echo(f"  平均亏损:  ${result.avg_loss:.2f}")
    typer.echo(f"  平均持仓:  {result.avg_duration_min:.0f} 分钟")
    typer.echo(f"{'=' * 50}")

    if result.trades:
        typer.echo("")
        typer.echo("最近交易:")
        for t in result.trades[-5:]:
            icon = "✅" if t.is_win else "❌"
            side = "多" if t.side.value == "long" else "空"
            typer.echo(f"  {icon} {side} {t.entry_price:.2f} → {t.exit_price:.2f} "
                       f"PnL=${t.pnl:.2f} ({t.reason_entry} → {t.reason_exit})")


@daytrade_app.command("scan")
def scan_cmd(
    instruments: str = typer.Option(
        "BTC-PERP,ETH-PERP",
        "-i",
        help="Comma-separated instruments to scan",
    ),
    strategy: str = typer.Option("ema_crossover", "-s", help="Strategy name"),
    interval: str = typer.Option("15m", help="Candle interval"),
    poll: int = typer.Option(60, help="Poll interval in seconds"),
    lookback: int = typer.Option(3, help="Lookback days for candle history"),
    testnet: bool = typer.Option(False, help="Use testnet data"),
    desktop: bool = typer.Option(True, help="Enable desktop notifications"),
    sound: bool = typer.Option(True, help="Enable sound alerts"),
    webhook: str = typer.Option("", help="Webhook URL (Slack/Discord/Telegram)"),
    max_ticks: int = typer.Option(0, help="Max scan ticks (0 = unlimited)"),
):
    """Real-time signal scanner with notifications.

    Continuously monitors selected instruments and alerts you when
    a strategy signal fires. Supports terminal, desktop, sound, and webhook.

    Examples:
        hl daytrade scan -i BTC-PERP,ETH-PERP -s rsi_reversal
        hl daytrade scan -i BTC-PERP -s vwap_reversion --poll 120
        hl daytrade scan -i ETH-PERP --webhook https://hooks.slack.com/...
    """
    from daytrade.strategies import STRATEGY_REGISTRY
    from daytrade.scanner import run_scanner

    if strategy not in STRATEGY_REGISTRY:
        typer.echo(f"Unknown strategy: {strategy}")
        typer.echo(f"Available: {', '.join(STRATEGY_REGISTRY.keys())}")
        raise typer.Exit(1)

    inst_list = [s.strip() for s in instruments.split(",") if s.strip()]
    strat = STRATEGY_REGISTRY[strategy]()

    run_scanner(
        instruments=inst_list,
        strategy=strat,
        interval=interval,
        lookback_days=lookback,
        poll_seconds=poll,
        testnet=testnet,
        enable_desktop=desktop,
        enable_sound=sound,
        webhook_url=webhook,
        max_ticks=max_ticks,
    )


@daytrade_app.command("signals")
def signals_cmd(
    date: str = typer.Option("", help="Date (YYYY-MM-DD), default today"),
    tail: int = typer.Option(20, "-n", help="Show last N signals"),
):
    """View signal history log."""
    import datetime as dt
    from pathlib import Path

    if not date:
        date = dt.date.today().isoformat()

    log_path = Path(f"data/daytrade/signals/signals_{date}.jsonl")
    if not log_path.exists():
        typer.echo(f"No signals logged for {date}")
        raise typer.Exit(0)

    import json
    lines = log_path.read_text().strip().split("\n")
    for line in lines[-tail:]:
        entry = json.loads(line)
        side = "🟢 多" if entry["side"] == "long" else "🔴 空"
        typer.echo(
            f"  {entry['timestamp']}  {entry['instrument']:<14s}  {side}  "
            f"价格={entry['price']:.2f}  置信={entry['confidence']:.0f}%  "
            f"| {entry['reason']}"
        )


@daytrade_app.command("strategies")
def strategies_cmd():
    """List available daytrade strategies."""
    from daytrade.strategies import STRATEGY_REGISTRY, STRATEGY_DESCRIPTIONS

    typer.echo("可用的日内交易策略:\n")
    for name, desc in STRATEGY_DESCRIPTIONS.items():
        typer.echo(f"  {name:<20s} {desc}")
        cls = STRATEGY_REGISTRY[name]
        defaults = cls.default_params()
        ranges = cls.param_ranges()
        if defaults:
            params_str = ", ".join(f"{k}={v}" for k, v in defaults.items() if k in ranges)
            typer.echo(f"  {'':20s} 关键参数: {params_str}")
        typer.echo("")


@daytrade_app.command("fetch")
def fetch_cmd(
    instrument: str = typer.Option("BTC-PERP", "-i", help="Trading instrument"),
    interval: str = typer.Option("15m", help="Candle interval"),
    lookback: int = typer.Option(7, help="Lookback days"),
    output: str = typer.Option("data/daytrade/candles.csv", "-o", help="Output CSV path"),
    testnet: bool = typer.Option(False, help="Use testnet"),
):
    """Fetch and save candle data for offline backtesting."""
    from daytrade.backtest import fetch_candles_hl, save_candles_csv

    typer.echo(f"Fetching {instrument} {interval} candles ({lookback} days)...")
    candles = fetch_candles_hl(instrument, interval, lookback, testnet=testnet)

    if not candles:
        typer.echo("No candle data available.")
        raise typer.Exit(1)

    save_candles_csv(candles, output)
    typer.echo(f"Saved {len(candles)} candles to {output}")
