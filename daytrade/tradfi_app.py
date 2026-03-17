"""Streamlit GUI for TradFi — stocks, ETFs, commodities.

Launch: streamlit run daytrade/tradfi_app.py
Or:     hl daytrade tradfi
"""
from __future__ import annotations

import datetime
from typing import Dict, List

import streamlit as st

st.set_page_config(
    page_title="Nunchi TradFi",
    page_icon="🏛",
    layout="wide",
    initial_sidebar_state="expanded",
)

from daytrade.backtest import run_backtest
from daytrade.models import BacktestResult, Side
from daytrade.providers.yahoo import YahooFinanceProvider, TRADFI_INSTRUMENTS
from daytrade.tradfi_strategies import (
    COMMODITY_STRATEGIES, STOCK_STRATEGIES, ETF_STRATEGIES,
    COMMODITY_DESCRIPTIONS, STOCK_DESCRIPTIONS, ETF_DESCRIPTIONS,
)

_yf = YahooFinanceProvider()

# ---------------------------------------------------------------------------
# Instrument groups
# ---------------------------------------------------------------------------
COMMODITY_SYMBOLS = [i for i in TRADFI_INSTRUMENTS if i["category"] == "商品"]
STOCK_SYMBOLS = [i for i in TRADFI_INSTRUMENTS if i["category"] in ("个股", "加密个股")]
ETF_SYMBOLS = [i for i in TRADFI_INSTRUMENTS if i["category"] in ("美股指数", "板块", "债券", "波动率", "外汇")]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _fmt_ts(ts_ms: int) -> str:
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

    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)
    fig.add_trace(go.Scatter(x=ts, y=ema9, name="EMA 9", line=dict(color="#ff9800", width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=ts, y=ema21, name="EMA 21", line=dict(color="#2196f3", width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=ts, y=vwap_fn(candles), name="VWAP",
                             line=dict(color="#9c27b0", width=1, dash="dot")), row=1, col=1)

    upper, mid, lower = bollinger_bands(closes)
    fig.add_trace(go.Scatter(x=ts, y=upper, name="BB上轨", line=dict(color="rgba(150,150,150,0.3)", width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=ts, y=lower, name="BB下轨", line=dict(color="rgba(150,150,150,0.3)", width=1),
                             fill="tonexty", fillcolor="rgba(150,150,150,0.05)"), row=1, col=1)

    for t in result.trades:
        edt = datetime.datetime.fromtimestamp(t.entry_time / 1000, tz=datetime.timezone.utc)
        xdt = datetime.datetime.fromtimestamp(t.exit_time / 1000, tz=datetime.timezone.utc)
        c = "#26a69a" if t.is_win else "#ef5350"
        s = "triangle-up" if t.side == Side.LONG else "triangle-down"
        fig.add_trace(go.Scatter(x=[edt], y=[t.entry_price], mode="markers", name="",
                                 marker=dict(symbol=s, size=12, color=c, line=dict(width=1, color="white")),
                                 showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=[xdt], y=[t.exit_price], mode="markers", name="",
                                 marker=dict(symbol="x", size=10, color=c), showlegend=False), row=1, col=1)

    vc = ["#26a69a" if c.close >= c.open else "#ef5350" for c in candles]
    fig.add_trace(go.Bar(x=ts, y=[c.volume for c in candles], name="成交量", marker_color=vc, opacity=0.5), row=2, col=1)

    rsi_vals = rsi(closes, 14)
    fig.add_trace(go.Scatter(x=ts, y=[v if v == v else None for v in rsi_vals], name="RSI",
                             line=dict(color="#ff9800", width=1)), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.3, row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.3, row=3, col=1)

    fig.update_layout(height=700, template="plotly_dark", xaxis_rangeslider_visible=False,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                      margin=dict(l=50, r=50, t=30, b=30))
    st.plotly_chart(fig, use_container_width=True)


def _render_equity(result):
    import plotly.graph_objects as go
    if not result.equity_curve:
        st.info("无交易记录")
        return
    fig = go.Figure()
    fig.add_trace(go.Scatter(y=result.equity_curve, mode="lines", name="权益",
                             line=dict(color="#26a69a" if result.net_pnl >= 0 else "#ef5350", width=2),
                             fill="tozeroy", fillcolor="rgba(38,166,154,0.1)" if result.net_pnl >= 0 else "rgba(239,83,80,0.1)"))
    peak = result.equity_curve[0]
    dd = []
    for v in result.equity_curve:
        if v > peak: peak = v
        dd.append(v - peak)
    fig.add_trace(go.Scatter(y=dd, mode="lines", name="回撤", line=dict(color="#ef5350", width=1),
                             fill="tozeroy", fillcolor="rgba(239,83,80,0.15)"))
    fig.update_layout(height=350, template="plotly_dark", yaxis_title="PnL ($)", margin=dict(l=50, r=50, t=10, b=30))
    st.plotly_chart(fig, use_container_width=True)


def _render_trades(result):
    if not result.trades:
        st.info("无交易记录")
        return
    import pandas as pd
    import plotly.graph_objects as go
    data = [{"方向": "🟢 多" if t.side == Side.LONG else "🔴 空",
             "入场": _fmt_ts(t.entry_time), "入场价": f"{t.entry_price:.2f}",
             "出场": _fmt_ts(t.exit_time), "出场价": f"{t.exit_price:.2f}",
             "盈亏": f"${t.pnl:.2f}", "盈亏%": f"{t.pnl_pct:.2f}%",
             "分钟": f"{t.duration_min:.0f}", "入场理由": t.reason_entry,
             "出场理由": t.reason_exit, "结果": "✅" if t.is_win else "❌"}
            for t in result.trades]
    st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        pnls = [t.pnl for t in result.trades]
        fig = go.Figure(go.Bar(y=pnls, marker_color=["#26a69a" if p >= 0 else "#ef5350" for p in pnls]))
        fig.update_layout(title="逐笔盈亏", height=300, template="plotly_dark", margin=dict(l=50, r=20, t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = go.Figure(go.Pie(labels=["盈利", "亏损"], values=[result.wins, result.losses],
                               marker_colors=["#26a69a", "#ef5350"], hole=0.4))
        fig.update_layout(title="胜负比", height=300, template="plotly_dark", margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)


def _render_metrics(r):
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("交易次数", r.total_trades)
    m2.metric("胜率", f"{r.win_rate:.1f}%")
    m3.metric("净盈亏", f"${r.net_pnl:.2f}", delta=f"${r.net_pnl:.2f}",
              delta_color="normal" if r.net_pnl >= 0 else "inverse")
    m4.metric("盈亏比", f"{r.profit_factor:.2f}")
    m5.metric("最大回撤", f"{r.max_drawdown_pct:.1f}%")
    m6.metric("Sharpe", f"{r.sharpe_ratio:.2f}")


def _run_scan(symbols, strategies, descriptions, interval, lookback):
    """Run all strategies of a category against selected symbols."""
    all_results = []
    cache = {}
    total = len(symbols) * len(strategies)
    progress = st.progress(0, text="扫描中...")
    done = 0

    for sym in symbols:
        if sym not in cache:
            cache[sym] = _yf.fetch_candles(sym, interval, lookback)
        candles = cache[sym]
        if not candles:
            for sn in strategies:
                all_results.append({"symbol": sym, "strategy": sn, "status": "error", "message": "无数据"})
                done += 1
            progress.progress(done / total)
            continue

        latest = candles[-1]
        for sn, scls in strategies.items():
            try:
                strat = scls()
                strat.reset()
                signal = None
                for idx, c in enumerate(candles):
                    sig = strat.on_candle(c, candles[:idx + 1])
                    if sig is not None and idx == len(candles) - 1:
                        signal = sig
                if signal:
                    all_results.append({"symbol": sym, "strategy": sn, "status": "signal",
                                        "signal": signal, "price": latest.close})
                else:
                    all_results.append({"symbol": sym, "strategy": sn, "status": "no_signal",
                                        "price": latest.close})
            except Exception as e:
                all_results.append({"symbol": sym, "strategy": sn, "status": "error", "message": str(e)})
            done += 1
            progress.progress(done / total, text=f"{sym} / {sn}")

    progress.empty()
    return all_results


def _display_scan(results):
    import pandas as pd
    has = [r for r in results if r["status"] == "signal"]
    no = [r for r in results if r["status"] == "no_signal"]
    err = [r for r in results if r["status"] == "error"]

    s1, s2, s3 = st.columns(3)
    s1.metric("触发信号", len(has))
    s2.metric("无信号", len(no))
    s3.metric("错误", len(err))

    if has:
        st.markdown("### 🎯 信号")
        for r in has:
            sig = r["signal"]
            icon = "🟢" if sig.side == Side.LONG else "🔴"
            side = "做多" if sig.side == Side.LONG else "做空"
            st.success(f"**{icon} {r['symbol']}** — {side} | 策略: **{r['strategy']}** | "
                       f"价格: {sig.price:.2f} | 置信度: {sig.confidence:.0f}% | {sig.reason}")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("当前价", f"{r['price']:.2f}")
            c2.metric("信号价", f"{sig.price:.2f}")
            if sig.stop_loss: c3.metric("止损", f"{sig.stop_loss:.2f}")
            if sig.take_profit: c4.metric("止盈", f"{sig.take_profit:.2f}")

    st.markdown("### 📋 扫描矩阵")
    rows = []
    for r in results:
        if r["status"] == "signal":
            sig = r["signal"]
            rows.append({"品种": r["symbol"], "策略": r["strategy"],
                         "信号": "🟢 多" if sig.side == Side.LONG else "🔴 空",
                         "价格": f"{sig.price:.2f}", "置信度": f"{sig.confidence:.0f}%",
                         "原因": sig.reason})
        elif r["status"] == "no_signal":
            rows.append({"品种": r["symbol"], "策略": r["strategy"],
                         "信号": "— 无", "价格": f"{r['price']:.2f}", "置信度": "—", "原因": ""})
        else:
            rows.append({"品种": r["symbol"], "策略": r["strategy"],
                         "信号": "❌", "价格": "—", "置信度": "—", "原因": r.get("message", "")})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Shared sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("🏛 Nunchi TradFi")
st.sidebar.markdown("传统金融 · 长线投资择时")

interval = st.sidebar.selectbox("K 线周期", ["1d", "1wk", "1h", "4h"], index=0)
lookback = st.sidebar.slider("回溯天数", 30, 730, 180)
position_size = st.sidebar.number_input("仓位大小 (股/手)", value=10.0, min_value=0.1, step=1.0)

st.sidebar.markdown("---")
st.sidebar.markdown("数据来源: **Yahoo Finance**")
st.sidebar.markdown("策略类型: **长线持有** (数周~数月)")
st.sidebar.markdown("费率: ETF/股票 1 bps, 商品 2 bps")


# ---------------------------------------------------------------------------
# Main: 3 tabs for 3 asset classes
# ---------------------------------------------------------------------------
tab_commodity, tab_stock, tab_etf = st.tabs(["🛢 大宗商品", "📈 个股", "📊 ETF"])

# ===================== COMMODITIES =====================
with tab_commodity:
    sub_bt, sub_sc = st.tabs(["📊 回测", "⚡ 信号扫描"])

    with sub_bt:
        st.subheader("🛢 大宗商品回测")
        st.caption("黄金 (GLD) · 白银 (SLV) · 原油 (USO) · 天然气 (UNG) · 金矿股 (GDX)")

        cm_sym = st.selectbox("品种", [i["symbol"] for i in COMMODITY_SYMBOLS],
                               format_func=lambda s: f"{s} — {next((i['name'] for i in COMMODITY_SYMBOLS if i['symbol']==s), s)}",
                               key="cm_sym")
        cm_strat = st.selectbox("策略", list(COMMODITY_STRATEGIES.keys()),
                                 format_func=lambda k: f"{k} — {COMMODITY_DESCRIPTIONS[k]}", key="cm_strat")

        # Strategy params
        scls = COMMODITY_STRATEGIES[cm_strat]
        cm_params = {}
        with st.expander("策略参数"):
            for k, v in scls.default_params().items():
                if k in scls.param_ranges():
                    lo, hi, step = scls.param_ranges()[k]
                    cm_params[k] = st.slider(k, float(lo), float(hi), float(v), float(step), key=f"cm_{k}")
                else:
                    cm_params[k] = v

        if st.button("🚀 运行回测", type="primary", key="cm_run"):
            with st.spinner(f"获取 {cm_sym} 数据..."):
                candles = _yf.fetch_candles(cm_sym, interval, lookback)
            if not candles:
                st.error("无数据")
            else:
                st.success(f"{len(candles)} 根 K 线 ({_fmt_ts(candles[0].timestamp_ms)} → {_fmt_ts(candles[-1].timestamp_ms)})")
                result = run_backtest(scls(params=cm_params), candles, cm_sym, size=position_size, fee_bps=2.0)
                _render_metrics(result)
                t1, t2, t3 = st.tabs(["K线", "权益", "明细"])
                with t1: _render_price_chart(candles, result)
                with t2: _render_equity(result)
                with t3: _render_trades(result)

    with sub_sc:
        st.subheader("⚡ 大宗商品信号扫描")
        cm_scan_syms = st.multiselect("品种", [i["symbol"] for i in COMMODITY_SYMBOLS],
                                       default=["GLD", "SLV", "USO"], key="cm_scan")
        if st.button("🔍 扫描", type="primary", key="cm_scan_btn") and cm_scan_syms:
            r = _run_scan(cm_scan_syms, COMMODITY_STRATEGIES, COMMODITY_DESCRIPTIONS, interval, lookback)
            _display_scan(r)

# ===================== STOCKS =====================
with tab_stock:
    sub_bt, sub_sc = st.tabs(["📊 回测", "⚡ 信号扫描"])

    with sub_bt:
        st.subheader("📈 个股回测")
        st.caption("科技股: AAPL MSFT NVDA TSLA | 加密股: COIN MSTR MARA RIOT IBIT")

        stk_sym = st.selectbox("品种", [i["symbol"] for i in STOCK_SYMBOLS],
                                format_func=lambda s: f"{s} — {next((i['name'] for i in STOCK_SYMBOLS if i['symbol']==s), s)}",
                                key="stk_sym")
        stk_custom = st.text_input("或输入自定义代码", "", key="stk_custom", placeholder="例: BABA, AMD, COIN")
        use_stk = stk_custom.strip().upper() if stk_custom.strip() else stk_sym

        stk_strat = st.selectbox("策略", list(STOCK_STRATEGIES.keys()),
                                  format_func=lambda k: f"{k} — {STOCK_DESCRIPTIONS[k]}", key="stk_strat")

        scls = STOCK_STRATEGIES[stk_strat]
        stk_params = {}
        with st.expander("策略参数"):
            for k, v in scls.default_params().items():
                if k in scls.param_ranges():
                    lo, hi, step = scls.param_ranges()[k]
                    if isinstance(v, int):
                        stk_params[k] = st.slider(k, int(lo), int(hi), int(v), int(step), key=f"stk_{k}")
                    else:
                        stk_params[k] = st.slider(k, float(lo), float(hi), float(v), float(step), key=f"stk_{k}")
                else:
                    stk_params[k] = v

        if st.button("🚀 运行回测", type="primary", key="stk_run"):
            with st.spinner(f"获取 {use_stk} 数据..."):
                candles = _yf.fetch_candles(use_stk, interval, lookback)
            if not candles:
                st.error(f"无法获取 {use_stk} 数据")
            else:
                st.success(f"{len(candles)} 根 K 线")
                result = run_backtest(scls(params=stk_params), candles, use_stk, size=position_size, fee_bps=1.0)
                _render_metrics(result)
                t1, t2, t3 = st.tabs(["K线", "权益", "明细"])
                with t1: _render_price_chart(candles, result)
                with t2: _render_equity(result)
                with t3: _render_trades(result)

    with sub_sc:
        st.subheader("⚡ 个股信号扫描")
        stk_scan_syms = st.multiselect("品种", [i["symbol"] for i in STOCK_SYMBOLS],
                                        default=["NVDA", "TSLA", "AAPL"], key="stk_scan")
        if st.button("🔍 扫描", type="primary", key="stk_scan_btn") and stk_scan_syms:
            r = _run_scan(stk_scan_syms, STOCK_STRATEGIES, STOCK_DESCRIPTIONS, interval, lookback)
            _display_scan(r)

# ===================== ETFs =====================
with tab_etf:
    sub_bt, sub_sc = st.tabs(["📊 回测", "⚡ 信号扫描"])

    with sub_bt:
        st.subheader("📊 ETF 回测")
        st.caption("指数 · 板块 · 债券 · 波动率 · 外汇 ETF")

        etf_cat = st.selectbox("类别", ["全部"] + sorted(set(i["category"] for i in ETF_SYMBOLS)), key="etf_cat")
        if etf_cat == "全部":
            etf_filtered = ETF_SYMBOLS
        else:
            etf_filtered = [i for i in ETF_SYMBOLS if i["category"] == etf_cat]

        etf_sym = st.selectbox("品种", [i["symbol"] for i in etf_filtered],
                                format_func=lambda s: f"{s} — {next((i['name'] for i in etf_filtered if i['symbol']==s), s)}",
                                key="etf_sym")

        etf_strat = st.selectbox("策略", list(ETF_STRATEGIES.keys()),
                                  format_func=lambda k: f"{k} — {ETF_DESCRIPTIONS[k]}", key="etf_strat")

        scls = ETF_STRATEGIES[etf_strat]
        etf_params = {}
        with st.expander("策略参数"):
            for k, v in scls.default_params().items():
                if k in scls.param_ranges():
                    lo, hi, step = scls.param_ranges()[k]
                    if isinstance(v, int):
                        etf_params[k] = st.slider(k, int(lo), int(hi), int(v), int(step), key=f"etf_{k}")
                    else:
                        etf_params[k] = st.slider(k, float(lo), float(hi), float(v), float(step), key=f"etf_{k}")
                else:
                    etf_params[k] = v

        if st.button("🚀 运行回测", type="primary", key="etf_run"):
            with st.spinner(f"获取 {etf_sym} 数据..."):
                candles = _yf.fetch_candles(etf_sym, interval, lookback)
            if not candles:
                st.error("无数据")
            else:
                st.success(f"{len(candles)} 根 K 线")
                result = run_backtest(scls(params=etf_params), candles, etf_sym, size=position_size, fee_bps=1.0)
                _render_metrics(result)
                t1, t2, t3 = st.tabs(["K线", "权益", "明细"])
                with t1: _render_price_chart(candles, result)
                with t2: _render_equity(result)
                with t3: _render_trades(result)

    with sub_sc:
        st.subheader("⚡ ETF 信号扫描")
        etf_scan_syms = st.multiselect("品种", [i["symbol"] for i in ETF_SYMBOLS],
                                        default=["SPY", "QQQ", "TLT"], key="etf_scan")
        if st.button("🔍 扫描", type="primary", key="etf_scan_btn") and etf_scan_syms:
            r = _run_scan(etf_scan_syms, ETF_STRATEGIES, ETF_DESCRIPTIONS, interval, lookback)
            _display_scan(r)
