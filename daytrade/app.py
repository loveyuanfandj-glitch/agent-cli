"""Streamlit GUI for crypto daytrade — BTC, ETH, and Hyperliquid perps.

Launch: streamlit run daytrade/app.py
Or:     hl daytrade ui
"""
from __future__ import annotations

import datetime
from typing import Dict, List

import streamlit as st

st.set_page_config(page_title="Nunchi Crypto Daytrade", page_icon="🪙", layout="wide",
                   initial_sidebar_state="expanded")

from daytrade.strategies import STRATEGY_REGISTRY, STRATEGY_DESCRIPTIONS
from daytrade.backtest import run_backtest
from daytrade.models import BacktestResult, Side
from daytrade.providers import HyperliquidProvider

_hl = HyperliquidProvider(testnet=False)
_instruments = [i["symbol"] for i in _hl.list_instruments()]


def _fmt_ts(ts_ms): return datetime.datetime.fromtimestamp(ts_ms / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")


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
        st.info("无交易"); return
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
    fig.update_layout(height=350, template="plotly_dark", yaxis_title="PnL ($)", margin=dict(l=50, r=50, t=10, b=30))
    st.plotly_chart(fig, use_container_width=True)


def _render_trades(r):
    if not r.trades: st.info("无交易"); return
    import pandas as pd; import plotly.graph_objects as go
    data = [{"方向": "🟢 多" if t.side == Side.LONG else "🔴 空", "入场": _fmt_ts(t.entry_time),
             "入场价": f"{t.entry_price:.2f}", "出场": _fmt_ts(t.exit_time), "出场价": f"{t.exit_price:.2f}",
             "盈亏": f"${t.pnl:.2f}", "%": f"{t.pnl_pct:.2f}%", "分钟": f"{t.duration_min:.0f}",
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


# Sidebar
st.sidebar.title("🪙 Crypto 日内择时")
instrument = st.sidebar.selectbox("品种", _instruments, index=0)
strategy_name = st.sidebar.selectbox("策略", list(STRATEGY_REGISTRY.keys()),
                                      format_func=lambda k: f"{k} — {STRATEGY_DESCRIPTIONS.get(k, '')}")
strategy_cls = STRATEGY_REGISTRY[strategy_name]

st.sidebar.markdown("### 参数")
defaults = strategy_cls.default_params(); ranges = strategy_cls.param_ranges(); params: Dict = {}
for key, dv in defaults.items():
    if key in ranges:
        lo, hi, step = ranges[key]
        params[key] = st.sidebar.slider(key, int(lo) if isinstance(dv, int) else float(lo),
                                         int(hi) if isinstance(dv, int) else float(hi),
                                         int(dv) if isinstance(dv, int) else float(dv),
                                         int(step) if isinstance(dv, int) else float(step))
    elif isinstance(dv, bool): params[key] = st.sidebar.checkbox(key, value=dv)
    elif isinstance(dv, (int, float)): params[key] = st.sidebar.number_input(key, value=dv)
    else: params[key] = dv

interval = st.sidebar.selectbox("K线周期", ["5m", "15m", "30m", "1h", "4h"], index=1)
lookback = st.sidebar.slider("回溯天数", 1, 30, 7)
size = st.sidebar.number_input("仓位", value=1.0, min_value=0.01, step=0.1)

st.sidebar.markdown("---")
st.sidebar.markdown("[🏛 打开 TradFi 工具](http://localhost:8502)")

# Main
tab_bt, tab_sc = st.tabs(["📊 回测", "⚡ 信号扫描"])

with tab_bt:
    st.subheader("🪙 加密货币回测")
    if st.button("🚀 运行回测", type="primary"):
        with st.spinner("获取数据..."):
            candles = _hl.fetch_candles(instrument, interval, lookback)
        if not candles:
            st.error("无数据"); st.stop()
        st.success(f"{len(candles)} 根 K 线 ({_fmt_ts(candles[0].timestamp_ms)} → {_fmt_ts(candles[-1].timestamp_ms)})")
        result = run_backtest(strategy_cls(params=params), candles, instrument, size=size)
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("交易", result.total_trades); m2.metric("胜率", f"{result.win_rate:.1f}%")
        m3.metric("PnL", f"${result.net_pnl:.2f}", delta=f"${result.net_pnl:.2f}",
                  delta_color="normal" if result.net_pnl >= 0 else "inverse")
        m4.metric("PF", f"{result.profit_factor:.2f}"); m5.metric("DD", f"{result.max_drawdown_pct:.1f}%")
        m6.metric("Sharpe", f"{result.sharpe_ratio:.2f}")
        t1, t2, t3 = st.tabs(["K线", "权益", "明细"])
        with t1: _render_price_chart(candles, result)
        with t2: _render_equity(result)
        with t3: _render_trades(result)

with tab_sc:
    st.subheader("⚡ 全策略扫描")
    scan_insts = st.multiselect("品种", _instruments, default=["BTC-PERP", "ETH-PERP"])
    if st.button("🔍 全策略扫描", type="primary") and scan_insts:
        cache = {}; results = []; total = len(scan_insts) * len(STRATEGY_REGISTRY); done = 0
        prog = st.progress(0)
        for inst in scan_insts:
            if inst not in cache: cache[inst] = _hl.fetch_candles(inst, interval, lookback)
            cs = cache[inst]
            if not cs:
                for sn in STRATEGY_REGISTRY: results.append({"instrument": inst, "strategy": sn, "status": "error"}); done += 1
                prog.progress(done / total); continue
            for sn, scls in STRATEGY_REGISTRY.items():
                strat = scls(); strat.reset(); sig = None
                for idx, c in enumerate(cs):
                    s = strat.on_candle(c, cs[:idx + 1])
                    if s and idx == len(cs) - 1: sig = s
                if sig: results.append({"instrument": inst, "strategy": sn, "status": "signal", "signal": sig, "price": cs[-1].close})
                else: results.append({"instrument": inst, "strategy": sn, "status": "no_signal", "price": cs[-1].close})
                done += 1; prog.progress(done / total)
        prog.empty()
        import pandas as pd
        has = [r for r in results if r["status"] == "signal"]
        s1, s2 = st.columns(2); s1.metric("信号", len(has)); s2.metric("无信号", len(results) - len(has))
        if has:
            for r in has:
                sig = r["signal"]; icon = "🟢" if sig.side == Side.LONG else "🔴"
                st.success(f"**{icon} {r['instrument']}** | **{r['strategy']}** | {sig.price:.2f} | {sig.reason}")
        rows = []
        for r in results:
            if r["status"] == "signal":
                sig = r["signal"]
                rows.append({"品种": r["instrument"], "策略": r["strategy"],
                             "信号": "🟢 多" if sig.side == Side.LONG else "🔴 空",
                             "价格": f"{sig.price:.2f}", "原因": sig.reason})
            elif r["status"] == "no_signal":
                rows.append({"品种": r["instrument"], "策略": r["strategy"], "信号": "—", "价格": f"{r['price']:.2f}", "原因": ""})
            else:
                rows.append({"品种": r["instrument"], "策略": r["strategy"], "信号": "❌", "价格": "—", "原因": "无数据"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
