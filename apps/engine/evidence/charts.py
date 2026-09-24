"""Shared presentation for financial research charts. Never resamples observations."""
import altair as alt
import pandas as pd
import streamlit as st

PALETTE = ["#3b82f6", "#ffffff", "#93c5fd", "#8b8b8b"]
NAMES = {"equity": "Net equity", "gross_same_positions": "Gross · same positions",
         "buy_hold_gross": "Buy & hold · gross", "pnl": "Net P&L", "arb_pnl": "Arbitrage P&L",
         "fees": "Cumulative fees", "fast_mid": "Reference mid", "slow_mid": "Slow venue mid",
         "bid_quote": "Bid quote", "ask_quote": "Ask quote", "inventory": "Inventory",
         "drawdown": "Drawdown", "net_pnl": "Net P&L"}


def finish(chart):
    return (chart.configure(background="#000000", font="Arial")
            .configure_view(stroke=None)
            .configure_axis(labelColor="#d4d4d4", titleColor="#ffffff", gridColor="#242424",
                            gridOpacity=.65, domain=False, tickColor="#404040", labelFontSize=11,
                            titleFontSize=11, titleFontWeight="normal", labelPadding=8, titlePadding=12)
            .configure_axisX(grid=False, labelAngle=0, labelOverlap=True, tickCount=6)
            .configure_axisY(orient="right", tickCount=5)
            .configure_legend(orient="top", title=None, labelColor="#ffffff", labelFontSize=11,
                              symbolStrokeWidth=2, padding=12))


def time_axis(field, values, title="Time (UTC)"):
    span = values.max()-values.min()
    fmt = "%d %b %H:%M" if span < pd.Timedelta(days=3) else "%d %b %y"
    return alt.X(field+":T", title=title, scale=alt.Scale(type="utc"),
                 axis=alt.Axis(format=fmt, tickCount=5, labelAngle=0))


def render(chart):
    st.altair_chart(finish(chart), theme=None, width="stretch")


def candles(frame, currency="Quote units"):
    frame = frame.tail(600).copy()
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    frame["utc_label"] = frame.timestamp.dt.strftime("%d %b %Y %H:%M")
    frame["Direction"] = frame.apply(lambda r: "Up / unchanged" if r.close >= r.open else "Down", axis=1)
    x = time_axis("timestamp", frame.timestamp)
    direction = alt.Color("Direction:N", scale=alt.Scale(domain=["Up / unchanged", "Down"], range=PALETTE[:2]))
    tooltip = [alt.Tooltip("utc_label:N", title="Bar (UTC)"),
               *[alt.Tooltip(c+":Q", title=c.title(), format=",.2f") for c in ["open", "high", "low", "close"]],
               alt.Tooltip("volume:Q", title="Volume", format=",.0f")]
    base = alt.Chart(frame).encode(x=x, color=direction, tooltip=tooltip)
    price = (base.mark_rule(strokeWidth=1).encode(y=alt.Y("low:Q", title=currency, scale=alt.Scale(zero=False), axis=alt.Axis(format=",.2f")), y2="high:Q") +
             base.mark_bar(size=3).encode(y="open:Q", y2="close:Q")).properties(height=300)
    volume = base.mark_bar(opacity=.65).encode(y=alt.Y("volume:Q", title="Volume", scale=alt.Scale(zero=True), axis=alt.Axis(format="~s"))).properties(height=100)
    zoom = alt.selection_interval(name="price_volume_zoom", bind="scales", encodings=["x"])
    render(alt.vconcat(price.add_params(zoom), volume, spacing=18).resolve_scale(x="shared", color="shared"))
    st.caption("Price & volume · blue = up / unchanged, white = down · latest 600 bars at most · timestamps UTC. Studies use exchange-local dates.")


def detail_line(frame, columns, x_label, height=260, temporal=False, y_title="Value", number_format=",.2f", zero=False):
    data = frame[columns].copy()
    data.index.name = x_label
    data = data.reset_index().melt(id_vars=x_label, var_name="Series", value_name="Value")
    labels = [NAMES.get(c, c) for c in columns]
    data["Series"] = data.Series.map(lambda c: NAMES.get(c,c))
    if temporal:
        data[x_label] = pd.to_datetime(data[x_label], utc=True)
        data["utc_label"] = data[x_label].dt.strftime("%d %b %Y %H:%M")
    x = time_axis(x_label, data[x_label]) if temporal else alt.X(x_label+":Q", axis=alt.Axis(format=",.0f"))
    chart = alt.Chart(data).mark_line(strokeWidth=1.6).encode(
        x=x, y=alt.Y("Value:Q", title=y_title, scale=alt.Scale(zero=zero), axis=alt.Axis(format=number_format)),
        color=alt.Color("Series:N", sort=labels, scale=alt.Scale(domain=labels, range=PALETTE[:len(labels)])),
        strokeDash=alt.StrokeDash("Series:N", sort=labels),
        tooltip=[alt.Tooltip("utc_label:N", title="Time (UTC)") if temporal else alt.Tooltip(x_label+":Q", format=",.0f"),
                 "Series:N", alt.Tooltip("Value:Q", format=number_format)])
    render(chart.properties(height=height).add_params(alt.selection_interval(bind="scales", encodings=["x"])))


def risk_area(series, x_label="Time (UTC)", temporal=True, percent=True, height=140):
    frame = series.rename("Value").to_frame()
    frame.index.name = x_label
    frame = frame.reset_index()
    if temporal:
        frame[x_label] = pd.to_datetime(frame[x_label], utc=True)
        frame["utc_label"] = frame[x_label].dt.strftime("%d %b %Y %H:%M")
    x = time_axis(x_label, frame[x_label]) if temporal else alt.X(x_label+":Q", axis=alt.Axis(format=",.0f"))
    fmt, title = (".1%", "Drawdown") if percent else (",.0f", "Inventory · units")
    chart = alt.Chart(frame).mark_area(color=PALETTE[0], opacity=.3, line={"color":PALETTE[0], "strokeWidth":1.3}, interpolate="step-after").encode(
        x=x, y=alt.Y("Value:Q", title=title, scale=alt.Scale(zero=True), axis=alt.Axis(format=fmt)),
        tooltip=[alt.Tooltip("utc_label:N", title="Time (UTC)") if temporal else alt.Tooltip(x_label+":Q", format=",.0f"),
                 alt.Tooltip("Value:Q", title=title, format=fmt)])
    baseline = alt.Chart(pd.DataFrame({"zero":[0]})).mark_rule(color="#777777", strokeWidth=.7).encode(y="zero:Q")
    render((chart+baseline).properties(height=height))


def latency_bars(frame):
    chart = alt.Chart(frame).mark_bar(color=PALETTE[0], size=34).encode(
        x=alt.X("outbound_latency_ms:O", title="Configured outbound latency · ms", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("net_pnl:Q", title="Net P&L · scenario units", scale=alt.Scale(zero=True), axis=alt.Axis(format=",.2f")),
        tooltip=[alt.Tooltip("outbound_latency_ms:Q", title="Configured ms"),
                 alt.Tooltip("effective_ms:Q", title="Effective ms"), alt.Tooltip("net_pnl:Q", title="Net P&L", format=",.2f")])
    render(chart.properties(height=200))
