"""Live signal scanner — monitors candles and emits notifications on signals.

Supports: terminal output, macOS desktop notification, sound alert, webhook.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from daytrade.backtest import fetch_candles_hl, INSTRUMENTS
from daytrade.models import Candle, Signal, Side
from daytrade.strategies.base import DaytradeStrategy

log = logging.getLogger("daytrade.scanner")

# Signal log directory
SIGNAL_LOG_DIR = Path("data/daytrade/signals")


def _fmt_ts(ts_ms: int) -> str:
    return datetime.datetime.fromtimestamp(
        ts_ms / 1000, tz=datetime.timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S")


def _now_str() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).strftime("%H:%M:%S")


# ---------------------------------------------------------------------------
# Notification backends
# ---------------------------------------------------------------------------

def notify_terminal(instrument: str, signal: Signal, price: float):
    """Print a prominent signal alert to the terminal."""
    side_str = "🟢 做多 LONG" if signal.side == Side.LONG else "🔴 做空 SHORT"
    box_w = 56

    print()
    print(f"{'=' * box_w}")
    print(f"  ⚡ 信号触发 | {_now_str()} UTC")
    print(f"{'=' * box_w}")
    print(f"  品种:     {instrument}")
    print(f"  方向:     {side_str}")
    print(f"  价格:     {signal.price:.2f}")
    print(f"  原因:     {signal.reason}")
    print(f"  置信度:   {signal.confidence:.0f}%")
    if signal.stop_loss:
        print(f"  止损:     {signal.stop_loss:.2f}")
    if signal.take_profit:
        print(f"  止盈:     {signal.take_profit:.2f}")
    if signal.meta:
        for k, v in signal.meta.items():
            if isinstance(v, float):
                print(f"  {k}:  {v:.4f}")
    print(f"{'=' * box_w}")
    print()


def notify_desktop(instrument: str, signal: Signal, price: float):
    """Send a macOS / Linux desktop notification."""
    side_str = "做多" if signal.side == Side.LONG else "做空"
    title = f"Nunchi 信号: {instrument} {side_str}"
    body = f"{signal.reason}\n价格: {signal.price:.2f} | 置信度: {signal.confidence:.0f}%"

    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{body}" with title "{title}" sound name "Glass"'],
                capture_output=True, timeout=5,
            )
        elif system == "Linux":
            subprocess.run(
                ["notify-send", "-u", "critical", title, body],
                capture_output=True, timeout=5,
            )
    except Exception as e:
        log.debug("Desktop notification failed: %s", e)


def notify_sound(instrument: str, signal: Signal, price: float):
    """Play a system sound alert."""
    system = platform.system()
    try:
        if system == "Darwin":
            # Glass for long, Basso for short
            sound = "Glass" if signal.side == Side.LONG else "Basso"
            subprocess.run(
                ["afplay", f"/System/Library/Sounds/{sound}.aiff"],
                capture_output=True, timeout=5,
            )
        elif system == "Linux":
            subprocess.run(
                ["paplay", "/usr/share/sounds/freedesktop/stereo/bell.oga"],
                capture_output=True, timeout=5,
            )
    except Exception as e:
        log.debug("Sound alert failed: %s", e)


def notify_webhook(instrument: str, signal: Signal, price: float,
                   webhook_url: str = ""):
    """POST signal to a webhook URL (Slack, Discord, Telegram bot, etc.)."""
    url = webhook_url or os.environ.get("DAYTRADE_WEBHOOK_URL", "")
    if not url:
        return

    try:
        import urllib.request
        payload = json.dumps({
            "text": (
                f"⚡ *{instrument}* {'做多' if signal.side == Side.LONG else '做空'}\n"
                f"价格: {signal.price:.2f} | {signal.reason}\n"
                f"止损: {signal.stop_loss:.2f} | 止盈: {signal.take_profit:.2f}\n"
                f"置信度: {signal.confidence:.0f}%"
            ),
            "instrument": instrument,
            "side": signal.side.value,
            "price": signal.price,
            "reason": signal.reason,
            "confidence": signal.confidence,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "timestamp": _fmt_ts(signal.timestamp_ms),
        }).encode("utf-8")

        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.warning("Webhook notification failed: %s", e)


def _save_signal_log(instrument: str, signal: Signal):
    """Append signal to a JSONL log file."""
    SIGNAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    log_path = SIGNAL_LOG_DIR / f"signals_{today}.jsonl"

    entry = {
        "timestamp": _fmt_ts(signal.timestamp_ms),
        "instrument": instrument,
        "side": signal.side.value,
        "price": signal.price,
        "reason": signal.reason,
        "confidence": signal.confidence,
        "stop_loss": signal.stop_loss,
        "take_profit": signal.take_profit,
        "meta": signal.meta,
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Scanner loop
# ---------------------------------------------------------------------------

def run_scanner(
    instruments: List[str],
    strategy: DaytradeStrategy,
    interval: str = "15m",
    lookback_days: int = 3,
    poll_seconds: int = 60,
    testnet: bool = True,
    enable_desktop: bool = True,
    enable_sound: bool = True,
    webhook_url: str = "",
    max_ticks: int = 0,
):
    """Run the live signal scanner loop.

    Polls candle data every `poll_seconds`, runs the strategy, and fires
    notifications when a new signal is detected.
    """
    # Track last signal per instrument to avoid duplicates
    last_signal_ts: Dict[str, int] = {}
    # Keep separate strategy instances per instrument
    strat_instances: Dict[str, DaytradeStrategy] = {}

    for inst in instruments:
        s = strategy.__class__(params=strategy.params)
        s.reset()
        strat_instances[inst] = s

    tick = 0
    print(f"🔍 实时信号扫描启动")
    print(f"   品种: {', '.join(instruments)}")
    print(f"   策略: {strategy.name}")
    print(f"   周期: {interval} | 轮询: {poll_seconds}s")
    print(f"   通知: 终端{'✓' if True else '✗'} 桌面{'✓' if enable_desktop else '✗'} "
          f"声音{'✓' if enable_sound else '✗'} Webhook{'✓' if webhook_url else '✗'}")
    print(f"   按 Ctrl+C 停止")
    print()

    while True:
        tick += 1
        if max_ticks and tick > max_ticks:
            print("达到最大扫描次数，停止。")
            break

        for inst in instruments:
            try:
                candles = fetch_candles_hl(inst, interval, lookback_days, testnet=testnet)
                if not candles:
                    log.warning("[%s] 无法获取K线数据", inst)
                    continue

                strat = strat_instances[inst]
                latest = candles[-1]

                # Feed all candles to strategy
                signal = None
                strat.reset()
                for i, c in enumerate(candles):
                    history = candles[: i + 1]
                    sig = strat.on_candle(c, history)
                    if sig is not None and i == len(candles) - 1:
                        # Only care about signal on the latest candle
                        signal = sig

                if signal is None:
                    print(f"  [{_now_str()}] {inst:<14s} {latest.close:>10.2f}  —  无信号")
                    continue

                # Dedup: skip if same timestamp as last signal
                if last_signal_ts.get(inst) == signal.timestamp_ms:
                    continue
                last_signal_ts[inst] = signal.timestamp_ms

                # Fire notifications
                notify_terminal(inst, signal, latest.close)
                _save_signal_log(inst, signal)

                if enable_desktop:
                    notify_desktop(inst, signal, latest.close)
                if enable_sound:
                    notify_sound(inst, signal, latest.close)
                if webhook_url:
                    notify_webhook(inst, signal, latest.close, webhook_url)

            except Exception as e:
                log.error("[%s] 扫描异常: %s", inst, e)

        if max_ticks and tick >= max_ticks:
            break

        # Wait for next poll
        try:
            time.sleep(poll_seconds)
        except KeyboardInterrupt:
            print("\n扫描已停止。")
            break
