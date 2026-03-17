"""Streamlit GUI for HK market — Hong Kong ETFs and stocks.

Launch: streamlit run daytrade/hk_app.py
Or:     hl daytrade hk
"""
from __future__ import annotations

import datetime
import os
from typing import Dict, List

import streamlit as st

st.set_page_config(page_title="Nunchi 港股", page_icon="🇭🇰", layout="wide",
                   initial_sidebar_state="expanded")

from daytrade.backtest import run_backtest
from daytrade.models import BacktestResult, Side
from daytrade.providers.yahoo import YahooFinanceProvider
from daytrade.tradfi_strategies import (
    COMMODITY_STRATEGIES, STOCK_STRATEGIES, ETF_STRATEGIES,
    COMMODITY_DESCRIPTIONS, STOCK_DESCRIPTIONS, ETF_DESCRIPTIONS,
    HK_STRATEGIES, HK_DESCRIPTIONS,
)

_yf = YahooFinanceProvider()

# ---------------------------------------------------------------------------
# HK instrument groups
# ---------------------------------------------------------------------------
HK_INDEX_ETFS = [
    {"symbol": "2800.HK", "name": "盈富基金 (追踪恒生指数)", "category": "港股指数"},
    {"symbol": "2828.HK", "name": "恒生中国企业 ETF (H股)", "category": "港股指数"},
    {"symbol": "3067.HK", "name": "安硕恒生科技 ETF", "category": "港股指数"},
    {"symbol": "3033.HK", "name": "南方恒生科技 ETF", "category": "港股指数"},
    {"symbol": "2840.HK", "name": "SPDR 金 ETF (港股)", "category": "港股指数"},
    {"symbol": "3037.HK", "name": "南方恒生指数 ETF", "category": "港股指数"},
    {"symbol": "3188.HK", "name": "华夏沪深300 ETF", "category": "港股指数"},
    {"symbol": "2822.HK", "name": "南方 A50 ETF", "category": "港股指数"},
    {"symbol": "3032.HK", "name": "恒生科技反向 (-1x)", "category": "港股杠杆/反向"},
    {"symbol": "7226.HK", "name": "南方恒指 2x 杠杆", "category": "港股杠杆/反向"},
    {"symbol": "7552.HK", "name": "南方恒科 2x 杠杆", "category": "港股杠杆/反向"},
]

HK_SECTOR_ETFS = [
    {"symbol": "3174.HK", "name": "GX 中国电动车 ETF", "category": "港股板块"},
    {"symbol": "3191.HK", "name": "GX 中国半导体 ETF", "category": "港股板块"},
    {"symbol": "3186.HK", "name": "GX 中国生物科技 ETF", "category": "港股板块"},
    {"symbol": "3088.HK", "name": "华夏恒生 ESG ETF", "category": "港股板块"},
]

HK_STOCKS = [
    {"symbol": "0700.HK", "name": "腾讯控股", "category": "港股个股"},
    {"symbol": "9988.HK", "name": "阿里巴巴", "category": "港股个股"},
    {"symbol": "9618.HK", "name": "京东集团", "category": "港股个股"},
    {"symbol": "9888.HK", "name": "百度集团", "category": "港股个股"},
    {"symbol": "3690.HK", "name": "美团", "category": "港股个股"},
    {"symbol": "9999.HK", "name": "网易", "category": "港股个股"},
    {"symbol": "1810.HK", "name": "小米集团", "category": "港股个股"},
    {"symbol": "9868.HK", "name": "小鹏汽车", "category": "港股个股"},
    {"symbol": "9866.HK", "name": "蔚来汽车", "category": "港股个股"},
    {"symbol": "2015.HK", "name": "理想汽车", "category": "港股个股"},
    {"symbol": "0981.HK", "name": "中芯国际", "category": "港股个股"},
    {"symbol": "1211.HK", "name": "比亚迪", "category": "港股个股"},
    {"symbol": "0005.HK", "name": "汇丰控股", "category": "港股个股"},
    {"symbol": "0941.HK", "name": "中国移动", "category": "港股个股"},
    {"symbol": "2318.HK", "name": "中国平安", "category": "港股个股"},
    {"symbol": "1024.HK", "name": "快手", "category": "港股个股"},
]

ALL_HK = HK_INDEX_ETFS + HK_SECTOR_ETFS + HK_STOCKS

# Merge all strategies for HK
ALL_STRATEGIES = {**HK_STRATEGIES, **ETF_STRATEGIES, **STOCK_STRATEGIES, **COMMODITY_STRATEGIES}
ALL_DESCRIPTIONS = {**HK_DESCRIPTIONS, **ETF_DESCRIPTIONS, **STOCK_DESCRIPTIONS, **COMMODITY_DESCRIPTIONS}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _fmt_ts(ts_ms):
    return datetime.datetime.fromtimestamp(ts_ms / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")


def _render_price_chart(candles, result):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    from daytrade.indicators import ema, vwap as vwap_fn, rsi, bollinger_bands
    closes = [c.close for c in candles]
    ts = [datetime.datetime.fromtimestamp(c.timestamp_ms / 1000, tz=datetime.timezone.utc) for c in candles]
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                        row_heights=[0.6, 0.2, 0.2], subplot_titles=["价格/信号", "成交量", "RSI"])
    fig.add_trace(go.Candlestick(x=ts, open=[c.open for c in candles], high=[c.high for c in candles],
                                  low=[c.low for c in candles], close=closes, name="价格",
                                  increasing_line_color="#26a69a", decreasing_line_color="#ef5350"), row=1, col=1)
    fig.add_trace(go.Scatter(x=ts, y=ema(closes, 9), name="EMA9", line=dict(color="#ff9800", width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=ts, y=ema(closes, 21), name="EMA21", line=dict(color="#2196f3", width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=ts, y=vwap_fn(candles), name="VWAP", line=dict(color="#9c27b0", width=1, dash="dot")), row=1, col=1)
    upper, mid, lower = bollinger_bands(closes)
    fig.add_trace(go.Scatter(x=ts, y=upper, name="BB上", line=dict(color="rgba(150,150,150,0.3)", width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=ts, y=lower, name="BB下", line=dict(color="rgba(150,150,150,0.3)", width=1),
                             fill="tonexty", fillcolor="rgba(150,150,150,0.05)"), row=1, col=1)
    for t in result.trades:
        edt = datetime.datetime.fromtimestamp(t.entry_time / 1000, tz=datetime.timezone.utc)
        xdt = datetime.datetime.fromtimestamp(t.exit_time / 1000, tz=datetime.timezone.utc)
        c = "#26a69a" if t.is_win else "#ef5350"
        fig.add_trace(go.Scatter(x=[edt], y=[t.entry_price], mode="markers", name="",
                                 marker=dict(symbol="triangle-up" if t.side == Side.LONG else "triangle-down",
                                             size=12, color=c, line=dict(width=1, color="white")),
                                 showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=[xdt], y=[t.exit_price], mode="markers", name="",
                                 marker=dict(symbol="x", size=10, color=c), showlegend=False), row=1, col=1)
    vc = ["#26a69a" if c.close >= c.open else "#ef5350" for c in candles]
    fig.add_trace(go.Bar(x=ts, y=[c.volume for c in candles], name="Vol", marker_color=vc, opacity=0.5), row=2, col=1)
    rv = rsi(closes, 14)
    fig.add_trace(go.Scatter(x=ts, y=[v if v == v else None for v in rv], name="RSI", line=dict(color="#ff9800", width=1)), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.3, row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.3, row=3, col=1)
    fig.update_layout(height=700, template="plotly_dark", xaxis_rangeslider_visible=False,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                      margin=dict(l=50, r=50, t=30, b=30))
    st.plotly_chart(fig, use_container_width=True)


def _render_equity(r):
    import plotly.graph_objects as go
    if not r.equity_curve:
        st.info("无交易记录"); return
    fig = go.Figure()
    fig.add_trace(go.Scatter(y=r.equity_curve, mode="lines", name="权益",
                             line=dict(color="#26a69a" if r.net_pnl >= 0 else "#ef5350", width=2),
                             fill="tozeroy", fillcolor="rgba(38,166,154,0.1)" if r.net_pnl >= 0 else "rgba(239,83,80,0.1)"))
    peak = r.equity_curve[0]; dd = []
    for v in r.equity_curve:
        if v > peak: peak = v
        dd.append(v - peak)
    fig.add_trace(go.Scatter(y=dd, mode="lines", name="回撤", line=dict(color="#ef5350", width=1),
                             fill="tozeroy", fillcolor="rgba(239,83,80,0.15)"))
    fig.update_layout(height=350, template="plotly_dark", yaxis_title="PnL (HKD)", margin=dict(l=50, r=50, t=10, b=30))
    st.plotly_chart(fig, use_container_width=True)


def _render_trades(r):
    if not r.trades:
        st.info("无交易记录"); return
    import pandas as pd; import plotly.graph_objects as go
    data = [{"方向": "🟢 多" if t.side == Side.LONG else "🔴 空", "入场": _fmt_ts(t.entry_time),
             "入场价": f"{t.entry_price:.2f}", "出场": _fmt_ts(t.exit_time), "出场价": f"{t.exit_price:.2f}",
             "盈亏": f"${t.pnl:.2f}", "盈亏%": f"{t.pnl_pct:.2f}%", "天数": f"{t.duration_min / 1440:.0f}",
             "入场理由": t.reason_entry, "出场理由": t.reason_exit, "": "✅" if t.is_win else "❌"} for t in r.trades]
    st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
    c1, c2 = st.columns(2)
    with c1:
        pnls = [t.pnl for t in r.trades]
        fig = go.Figure(go.Bar(y=pnls, marker_color=["#26a69a" if p >= 0 else "#ef5350" for p in pnls]))
        fig.update_layout(title="逐笔盈亏", height=300, template="plotly_dark", margin=dict(l=50, r=20, t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = go.Figure(go.Pie(labels=["盈", "亏"], values=[r.wins, r.losses], marker_colors=["#26a69a", "#ef5350"], hole=0.4))
        fig.update_layout(title="胜负", height=300, template="plotly_dark", margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)


def _render_metrics(r):
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("交易次数", r.total_trades); m2.metric("胜率", f"{r.win_rate:.1f}%")
    m3.metric("净盈亏", f"${r.net_pnl:.2f}", delta=f"${r.net_pnl:.2f}",
              delta_color="normal" if r.net_pnl >= 0 else "inverse")
    m4.metric("盈亏比", f"{r.profit_factor:.2f}"); m5.metric("最大回撤", f"{r.max_drawdown_pct:.1f}%")
    m6.metric("Sharpe", f"{r.sharpe_ratio:.2f}")


def _run_scan(symbols, strategies, descriptions, interval, lookback):
    all_results = []; cache = {}
    total = len(symbols) * len(strategies)
    prog = st.progress(0, text="扫描中..."); done = 0
    for sym in symbols:
        if sym not in cache:
            cache[sym] = _yf.fetch_candles(sym, interval, lookback)
        cs = cache[sym]
        if not cs:
            for sn in strategies:
                all_results.append({"symbol": sym, "strategy": sn, "status": "error", "message": "无数据"}); done += 1
            prog.progress(done / total); continue
        latest = cs[-1]
        for sn, scls in strategies.items():
            try:
                strat = scls(); strat.reset(); signal = None
                for idx, c in enumerate(cs):
                    sig = strat.on_candle(c, cs[:idx + 1])
                    if sig is not None and idx == len(cs) - 1: signal = sig
                if signal:
                    all_results.append({"symbol": sym, "strategy": sn, "status": "signal", "signal": signal, "price": latest.close})
                else:
                    all_results.append({"symbol": sym, "strategy": sn, "status": "no_signal", "price": latest.close})
            except Exception as e:
                all_results.append({"symbol": sym, "strategy": sn, "status": "error", "message": str(e)})
            done += 1; prog.progress(done / total, text=f"{sym} / {sn}")
    prog.empty()
    return all_results


def _send_desktop_notify(title: str, body: str):
    """Send macOS desktop notification for buy signals."""
    import subprocess, platform
    try:
        if platform.system() == "Darwin":
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{body}" with title "{title}" sound name "Glass"'],
                capture_output=True, timeout=5,
            )
    except Exception:
        pass


def _display_scan(results):
    import pandas as pd
    has = [r for r in results if r["status"] == "signal"]
    buy_signals = [r for r in has if r["signal"].side == Side.LONG]
    sell_signals = [r for r in has if r["signal"].side == Side.SHORT]
    no_signal = [r for r in results if r["status"] == "no_signal"]
    errors = [r for r in results if r["status"] == "error"]

    # Summary with buy/sell split
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("🟢 买入信号", len(buy_signals))
    s2.metric("🔴 卖出信号", len(sell_signals))
    s3.metric("无信号", len(no_signal))
    s4.metric("错误", len(errors))

    # ===== BUY SIGNALS (prominent) =====
    if buy_signals:
        st.markdown("---")
        st.markdown("## 🟢 买入提示")
        st.caption("以下品种触发了买入信号，建议关注")

        # Desktop + Feishu notifications
        buy_names = []
        for r in buy_signals:
            name = next((i["name"] for i in ALL_HK if i["symbol"] == r["symbol"]), r["symbol"])
            buy_names.append(f"{r['symbol']} {name}")
        if buy_names:
            _send_desktop_notify(
                f"🟢 {len(buy_names)} 个买入信号",
                " | ".join(buy_names[:5]),
            )

        # Feishu notifications
        from daytrade.notify_feishu import notify_buy_signal, notify_sell_signal, notify_scan_summary
        feishu_url = st.session_state.get("feishu_webhook", "")
        if feishu_url:
            for r in buy_signals:
                name = next((i["name"] for i in ALL_HK if i["symbol"] == r["symbol"]), r["symbol"])
                notify_buy_signal(r["symbol"], name, r["signal"], r["price"], r["strategy"], feishu_url)
            for r in sell_signals:
                name = next((i["name"] for i in ALL_HK if i["symbol"] == r["symbol"]), r["symbol"])
                notify_sell_signal(r["symbol"], name, r["signal"], r["price"], r["strategy"], feishu_url)
            notify_scan_summary(buy_signals, sell_signals, "港股", feishu_url)

        for r in buy_signals:
            sig = r["signal"]
            name = next((i["name"] for i in ALL_HK if i["symbol"] == r["symbol"]), r["symbol"])
            st.success(
                f"### 🟢 买入: {r['symbol']} {name}\n"
                f"策略: **{r['strategy']}** | 信号价: **{sig.price:.2f}** | "
                f"置信度: {sig.confidence:.0f}% | {sig.reason}"
            )
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("当前价", f"{r['price']:.2f}")
            c2.metric("建议买入价", f"{sig.price:.2f}")
            if sig.stop_loss:
                risk_pct = abs(sig.price - sig.stop_loss) / sig.price * 100
                c3.metric("止损价", f"{sig.stop_loss:.2f}", delta=f"-{risk_pct:.1f}%", delta_color="inverse")
            if sig.take_profit:
                reward_pct = abs(sig.take_profit - sig.price) / sig.price * 100
                c4.metric("目标价", f"{sig.take_profit:.2f}", delta=f"+{reward_pct:.1f}%")

    # ===== SELL SIGNALS =====
    if sell_signals:
        st.markdown("---")
        st.markdown("## 🔴 卖出/止损提示")
        st.caption("以下品种触发了卖出信号，持仓者注意")

        for r in sell_signals:
            sig = r["signal"]
            name = next((i["name"] for i in ALL_HK if i["symbol"] == r["symbol"]), r["symbol"])
            st.error(
                f"**🔴 {r['symbol']} {name}** | 策略: **{r['strategy']}** | "
                f"价格: {sig.price:.2f} | {sig.reason}"
            )
            c1, c2 = st.columns(2)
            c1.metric("当前价", f"{r['price']:.2f}")
            c2.metric("信号价", f"{sig.price:.2f}")

    # ===== NO SIGNAL =====
    if not buy_signals and not sell_signals:
        st.info("当前无任何买入或卖出信号，市场暂时观望。")

    # ===== FULL MATRIX =====
    st.markdown("---")
    st.markdown("### 📋 扫描矩阵")
    rows = []
    for r in results:
        name = next((i["name"] for i in ALL_HK if i["symbol"] == r["symbol"]), r["symbol"])
        if r["status"] == "signal":
            sig = r["signal"]
            rows.append({"代码": r["symbol"], "名称": name, "策略": r["strategy"],
                         "信号": "🟢 买入" if sig.side == Side.LONG else "🔴 卖出",
                         "价格": f"{sig.price:.2f}",
                         "止损": f"{sig.stop_loss:.2f}" if sig.stop_loss else "—",
                         "目标": f"{sig.take_profit:.2f}" if sig.take_profit else "—",
                         "原因": sig.reason})
        elif r["status"] == "no_signal":
            rows.append({"代码": r["symbol"], "名称": name, "策略": r["strategy"],
                         "信号": "— 观望", "价格": f"{r['price']:.2f}",
                         "止损": "—", "目标": "—", "原因": ""})
        else:
            rows.append({"代码": r["symbol"], "名称": name, "策略": r["strategy"],
                         "信号": "❌ 错误", "价格": "—",
                         "止损": "—", "目标": "—", "原因": r.get("message", "")})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("🇭🇰 港股择时")
st.sidebar.markdown("港股 ETF · 个股 · 长线持有")

interval = st.sidebar.selectbox("K 线周期", ["1d", "1wk"], index=0)
lookback = st.sidebar.slider("回溯天数", 30, 730, 365)
position_size = st.sidebar.number_input("仓位 (股)", value=1000.0, min_value=100.0, step=100.0)

st.sidebar.markdown("---")
st.sidebar.markdown("### 飞书通知")
feishu_url = st.sidebar.text_input(
    "飞书 Webhook URL",
    value=st.session_state.get("feishu_webhook", os.environ.get("FEISHU_WEBHOOK_URL", "")),
    type="password",
    placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
    key="feishu_input",
)
st.session_state["feishu_webhook"] = feishu_url
if feishu_url:
    st.sidebar.success("飞书通知已启用")
else:
    st.sidebar.caption("扫描到信号时自动推送到飞书群")

st.sidebar.markdown("---")
st.sidebar.markdown("数据来源: **Yahoo Finance**")
st.sidebar.markdown("费率: 港股约 5 bps (佣金+印花税)")
st.sidebar.markdown("---")
st.sidebar.markdown("[🪙 Crypto](http://localhost:8501) · [🏛 美股](http://localhost:8502)")


# ---------------------------------------------------------------------------
# Main: 3 tabs
# ---------------------------------------------------------------------------
tab_etf, tab_stock, tab_scan_all = st.tabs(["📊 港股 ETF", "📈 港股个股", "⚡ 全市场扫描"])

# ===================== ETF =====================
with tab_etf:
    sub_bt, sub_sc = st.tabs(["📊 回测", "⚡ 信号扫描"])

    with sub_bt:
        st.subheader("📊 港股 ETF 回测")
        st.caption("恒生指数 · 恒生科技 · H股 · 沪深300 · A50 · 杠杆/反向")

        all_etfs = HK_INDEX_ETFS + HK_SECTOR_ETFS
        etf_cat = st.selectbox("类别", ["全部"] + sorted(set(i["category"] for i in all_etfs)), key="hk_etf_cat")
        filtered = all_etfs if etf_cat == "全部" else [i for i in all_etfs if i["category"] == etf_cat]

        hk_sym = st.selectbox("品种", [i["symbol"] for i in filtered],
                               format_func=lambda s: f"{s} — {next((i['name'] for i in filtered if i['symbol']==s), s)}",
                               key="hk_etf_sym")

        _etf_hk_strats = {**HK_STRATEGIES, **ETF_STRATEGIES}
        _etf_hk_descs = {**HK_DESCRIPTIONS, **ETF_DESCRIPTIONS}
        hk_strat = st.selectbox("策略", list(_etf_hk_strats.keys()),
                                 format_func=lambda k: f"{k} — {_etf_hk_descs[k]}", key="hk_etf_strat")
        scls = _etf_hk_strats[hk_strat]

        with st.expander("策略参数"):
            p = {}
            for k, v in scls.default_params().items():
                if k in scls.param_ranges():
                    lo, hi, step = scls.param_ranges()[k]
                    if isinstance(v, int): p[k] = st.slider(k, int(lo), int(hi), int(v), int(step), key=f"hketf_{k}")
                    else: p[k] = st.slider(k, float(lo), float(hi), float(v), float(step), key=f"hketf_{k}")
                else: p[k] = v

        if st.button("🚀 运行回测", type="primary", key="hk_etf_run"):
            with st.spinner(f"获取 {hk_sym} 数据..."):
                candles = _yf.fetch_candles(hk_sym, interval, lookback)
            if not candles:
                st.error("无数据")
            else:
                st.success(f"{len(candles)} 根 K 线 ({_fmt_ts(candles[0].timestamp_ms)} → {_fmt_ts(candles[-1].timestamp_ms)})")
                result = run_backtest(scls(params=p), candles, hk_sym, size=position_size, fee_bps=5.0)
                _render_metrics(result)
                t1, t2, t3 = st.tabs(["K线", "权益", "明细"])
                with t1: _render_price_chart(candles, result)
                with t2: _render_equity(result)
                with t3: _render_trades(result)

    with sub_sc:
        st.subheader("⚡ 港股 ETF 信号扫描")
        etf_syms = st.multiselect("品种", [i["symbol"] for i in all_etfs],
                                   format_func=lambda s: f"{s} {next((i['name'] for i in all_etfs if i['symbol']==s), '')}",
                                   default=["2800.HK", "3067.HK", "2828.HK"], key="hk_etf_scan")
        if st.button("🔍 扫描", type="primary", key="hk_etf_scan_btn") and etf_syms:
            r = _run_scan(etf_syms, {**HK_STRATEGIES, **ETF_STRATEGIES}, {**HK_DESCRIPTIONS, **ETF_DESCRIPTIONS}, interval, lookback)
            _display_scan(r)

# ===================== STOCKS =====================
with tab_stock:
    sub_bt, sub_sc = st.tabs(["📊 回测", "⚡ 信号扫描"])

    with sub_bt:
        st.subheader("📈 港股个股回测")
        st.caption("腾讯 · 阿里 · 美团 · 小米 · 比亚迪 · 中芯 · 新能源车")

        stk_sym = st.selectbox("品种", [i["symbol"] for i in HK_STOCKS],
                                format_func=lambda s: f"{s} — {next((i['name'] for i in HK_STOCKS if i['symbol']==s), s)}",
                                key="hk_stk_sym")
        stk_custom = st.text_input("或输入港股代码", "", key="hk_custom", placeholder="例: 1398.HK, 0388.HK")
        use_sym = stk_custom.strip() if stk_custom.strip() else stk_sym

        _stk_hk_strats = {**HK_STRATEGIES, **STOCK_STRATEGIES}
        _stk_hk_descs = {**HK_DESCRIPTIONS, **STOCK_DESCRIPTIONS}
        stk_strat = st.selectbox("策略", list(_stk_hk_strats.keys()),
                                  format_func=lambda k: f"{k} — {_stk_hk_descs[k]}", key="hk_stk_strat")
        scls = _stk_hk_strats[stk_strat]

        with st.expander("策略参数"):
            p = {}
            for k, v in scls.default_params().items():
                if k in scls.param_ranges():
                    lo, hi, step = scls.param_ranges()[k]
                    if isinstance(v, int): p[k] = st.slider(k, int(lo), int(hi), int(v), int(step), key=f"hkstk_{k}")
                    else: p[k] = st.slider(k, float(lo), float(hi), float(v), float(step), key=f"hkstk_{k}")
                else: p[k] = v

        if st.button("🚀 运行回测", type="primary", key="hk_stk_run"):
            with st.spinner(f"获取 {use_sym} 数据..."):
                candles = _yf.fetch_candles(use_sym, interval, lookback)
            if not candles:
                st.error(f"无法获取 {use_sym} 数据")
            else:
                st.success(f"{len(candles)} 根 K 线")
                result = run_backtest(scls(params=p), candles, use_sym, size=position_size, fee_bps=5.0)
                _render_metrics(result)
                t1, t2, t3 = st.tabs(["K线", "权益", "明细"])
                with t1: _render_price_chart(candles, result)
                with t2: _render_equity(result)
                with t3: _render_trades(result)

    with sub_sc:
        st.subheader("⚡ 港股个股信号扫描")
        stk_syms = st.multiselect("品种", [i["symbol"] for i in HK_STOCKS],
                                   format_func=lambda s: f"{s} {next((i['name'] for i in HK_STOCKS if i['symbol']==s), '')}",
                                   default=["0700.HK", "9988.HK", "1810.HK", "1211.HK"], key="hk_stk_scan")
        if st.button("🔍 扫描", type="primary", key="hk_stk_scan_btn") and stk_syms:
            r = _run_scan(stk_syms, {**HK_STRATEGIES, **STOCK_STRATEGIES}, {**HK_DESCRIPTIONS, **STOCK_DESCRIPTIONS}, interval, lookback)
            _display_scan(r)

# ===================== FULL MARKET SCAN =====================
with tab_scan_all:
    st.subheader("⚡ 港股全市场扫描")
    st.caption("对所有 ETF + 个股运行全部策略")

    col1, col2 = st.columns(2)
    with col1:
        scan_etfs = st.checkbox("包含 ETF", value=True, key="hk_scan_etf")
    with col2:
        scan_stocks = st.checkbox("包含个股", value=True, key="hk_scan_stk")

    if st.button("🔍 全市场扫描", type="primary", key="hk_full_scan"):
        syms = []
        if scan_etfs:
            syms += [i["symbol"] for i in HK_INDEX_ETFS + HK_SECTOR_ETFS]
        if scan_stocks:
            syms += [i["symbol"] for i in HK_STOCKS]

        if syms:
            r = _run_scan(syms, ALL_STRATEGIES, ALL_DESCRIPTIONS, interval, lookback)
            _display_scan(r)
        else:
            st.warning("请至少选择一个类别")
