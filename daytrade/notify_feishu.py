"""Feishu (飞书) bot notification for trading signals."""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import List, Optional

from daytrade.models import Signal, Side

log = logging.getLogger("daytrade.feishu")

# Set via env var or pass directly
FEISHU_WEBHOOK_URL = os.environ.get(
    "FEISHU_WEBHOOK_URL",
    "https://open.larksuite.com/open-apis/bot/v2/hook/d559a4ab-dbae-4d3c-9a1f-42ef33c368af",
)


def send_feishu(
    title: str,
    content_lines: List[List[dict]],
    webhook_url: str = "",
) -> bool:
    """Send a rich-text message to Feishu bot.

    Args:
        title: Card title
        content_lines: Feishu rich-text content (list of lines, each line is list of elements)
        webhook_url: Webhook URL, falls back to FEISHU_WEBHOOK_URL env var
    """
    url = webhook_url or FEISHU_WEBHOOK_URL
    if not url:
        log.debug("No Feishu webhook URL configured")
        return False

    payload = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content_lines,
                }
            }
        }
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        if result.get("code") == 0:
            log.info("Feishu message sent: %s", title)
            return True
        else:
            log.warning("Feishu API error: %s", result)
            return False
    except Exception as e:
        log.warning("Feishu send failed: %s", e)
        return False


def notify_buy_signal(
    symbol: str,
    name: str,
    signal: Signal,
    current_price: float,
    strategy: str,
    webhook_url: str = "",
):
    """Send a buy signal notification to Feishu."""
    risk_pct = ""
    if signal.stop_loss:
        risk_pct = f" (-{abs(signal.price - signal.stop_loss) / signal.price * 100:.1f}%)"
    reward_pct = ""
    if signal.take_profit:
        reward_pct = f" (+{abs(signal.take_profit - signal.price) / signal.price * 100:.1f}%)"

    content = [
        [{"tag": "text", "text": f"品种: "}, {"tag": "text", "text": f"{symbol} {name}", "style": ["bold"]}],
        [{"tag": "text", "text": f"方向: "}, {"tag": "text", "text": "🟢 买入", "style": ["bold"]}],
        [{"tag": "text", "text": f"当前价: {current_price:.2f}  |  信号价: {signal.price:.2f}"}],
        [{"tag": "text", "text": f"策略: {strategy}"}],
        [{"tag": "text", "text": f"原因: {signal.reason}"}],
        [{"tag": "text", "text": f"置信度: {signal.confidence:.0f}%"}],
    ]
    if signal.stop_loss:
        content.append([{"tag": "text", "text": f"止损: {signal.stop_loss:.2f}{risk_pct}"}])
    if signal.take_profit:
        content.append([{"tag": "text", "text": f"目标: {signal.take_profit:.2f}{reward_pct}"}])

    send_feishu(f"🟢 买入信号: {symbol} {name}", content, webhook_url)


def notify_sell_signal(
    symbol: str,
    name: str,
    signal: Signal,
    current_price: float,
    strategy: str,
    webhook_url: str = "",
):
    """Send a sell signal notification to Feishu."""
    content = [
        [{"tag": "text", "text": f"品种: "}, {"tag": "text", "text": f"{symbol} {name}", "style": ["bold"]}],
        [{"tag": "text", "text": f"方向: "}, {"tag": "text", "text": "🔴 卖出", "style": ["bold"]}],
        [{"tag": "text", "text": f"当前价: {current_price:.2f}  |  信号价: {signal.price:.2f}"}],
        [{"tag": "text", "text": f"策略: {strategy}"}],
        [{"tag": "text", "text": f"原因: {signal.reason}"}],
    ]
    send_feishu(f"🔴 卖出信号: {symbol} {name}", content, webhook_url)


def notify_scan_summary(
    buy_signals: list,
    sell_signals: list,
    market: str = "港股",
    webhook_url: str = "",
):
    """Send a scan summary to Feishu."""
    if not buy_signals and not sell_signals:
        return

    content = [
        [{"tag": "text", "text": f"🟢 买入: {len(buy_signals)} 个  |  🔴 卖出: {len(sell_signals)} 个"}],
        [{"tag": "text", "text": ""}],
    ]

    if buy_signals:
        content.append([{"tag": "text", "text": "── 买入信号 ──", "style": ["bold"]}])
        for r in buy_signals[:10]:
            sig = r["signal"]
            sl_str = f"  止损:{sig.stop_loss:.2f}" if sig.stop_loss else ""
            tp_str = f"  目标:{sig.take_profit:.2f}" if sig.take_profit else ""
            content.append([{"tag": "text", "text":
                             f"🟢 {r['symbol']} @ {sig.price:.2f}  [{r['strategy']}]{sl_str}{tp_str}"}])

    if sell_signals:
        content.append([{"tag": "text", "text": ""}])
        content.append([{"tag": "text", "text": "── 卖出信号 ──", "style": ["bold"]}])
        for r in sell_signals[:10]:
            sig = r["signal"]
            content.append([{"tag": "text", "text":
                             f"🔴 {r['symbol']} @ {sig.price:.2f}  [{r['strategy']}] {sig.reason}"}])

    send_feishu(f"📊 {market}扫描报告 ({len(buy_signals)}买 {len(sell_signals)}卖)", content, webhook_url)
