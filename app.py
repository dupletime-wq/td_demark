from __future__ import annotations

import math
from typing import Iterable

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from data_provider import DataProviderError, download_price_data
from td_indicators import build_recent_signal_summary, build_signal_summary, compute_all_indicators


DEFAULT_WATCHLIST = "SPY, QQQ, AAPL, MSFT, NVDA, TSLA, BTC-USD, ETH-USD"
PERIOD_OPTIONS = ["3mo", "6mo", "1y", "2y", "5y", "10y"]
INTERVAL_OPTIONS = ["1d", "1wk", "1mo"]
DISPLAY_MODES = ["Precision", "Balanced", "Debug"]
SCANNER_LOOKBACK = 20
MAX_CHART_ROWS = 900
MAX_SIGNAL_MARKERS = 40
SIGNAL_COLUMNS = [
    "close",
    "signal_zone",
    "signal_side",
    "signal_quality",
    "signal_event",
    "signal_strength",
    "display_signal",
    "top_exhaustion_score",
    "bottom_exhaustion_score",
    "top_pressure",
    "bottom_pressure",
    "td_sell_setup",
    "td_buy_setup",
    "td_sell_countdown",
    "td_buy_countdown",
    "td_sell_combo",
    "td_buy_combo",
    "mfi",
    "bb_width",
]


st.set_page_config(
    page_title="TD DeMark Exhaustion Lab",
    page_icon="TD",
    layout="wide",
    initial_sidebar_state="auto",
)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg: #0b0f14;
            --panel: #111820;
            --panel-2: #151f2a;
            --line: rgba(188, 205, 219, 0.16);
            --text: #edf3f8;
            --muted: #91a2b2;
            --green: #41d38a;
            --red: #ff5c70;
            --amber: #f1bd4b;
            --cyan: #48b7ff;
        }
        .stApp {
            background:
                radial-gradient(circle at 15% 8%, rgba(72, 183, 255, 0.12), transparent 28%),
                linear-gradient(180deg, #0b0f14 0%, #0d131a 44%, #101820 100%);
            color: var(--text);
        }
        [data-testid="stHeader"] {
            background: rgba(11, 15, 20, 0.96);
            border-bottom: 1px solid var(--line);
        }
        .block-container {
            padding-top: 4.2rem;
            padding-bottom: 2.5rem;
            max-width: 1440px;
        }
        section[data-testid="stSidebar"] {
            background: #0a0e13;
            border-right: 1px solid var(--line);
        }
        [data-testid="stMetric"] {
            background: linear-gradient(180deg, rgba(21, 31, 42, 0.94), rgba(13, 20, 28, 0.94));
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 15px 16px;
            box-shadow: 0 18px 46px rgba(0, 0, 0, 0.20);
        }
        [data-testid="stMetricLabel"] p {
            color: var(--muted);
            font-size: 0.78rem;
        }
        [data-testid="stMetricValue"] {
            color: var(--text);
        }
        .title-row {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 20px;
            margin-bottom: 12px;
        }
        .title-row h1 {
            margin: 0;
            font-size: clamp(1.45rem, 2.2vw, 2.2rem);
            line-height: 1.08;
            letter-spacing: 0;
        }
        .title-row .sub {
            color: var(--muted);
            font-size: 0.92rem;
            margin-top: 6px;
        }
        .badge-row {
            display: flex;
            flex-wrap: wrap;
            justify-content: flex-end;
            gap: 8px;
        }
        .badge {
            border: 1px solid var(--line);
            border-radius: 999px;
            padding: 6px 10px;
            color: var(--muted);
            background: rgba(17, 24, 32, 0.72);
            font-size: 0.76rem;
            white-space: nowrap;
        }
        .notice {
            border: 1px solid rgba(241, 189, 75, 0.34);
            background: rgba(241, 189, 75, 0.09);
            color: #f6d58a;
            border-radius: 8px;
            padding: 10px 12px;
            font-size: 0.86rem;
            margin: 8px 0 16px 0;
        }
        .guide-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            margin: 10px 0 8px 0;
        }
        .guide-card {
            min-height: 132px;
            border: 1px solid var(--line);
            border-radius: 8px;
            background: linear-gradient(180deg, rgba(21, 31, 42, 0.84), rgba(13, 20, 28, 0.88));
            padding: 13px 14px;
        }
        .guide-card .kicker {
            color: var(--muted);
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        .guide-card .headline {
            color: var(--text);
            font-size: 1.02rem;
            font-weight: 700;
            margin: 8px 0 6px 0;
        }
        .guide-card .body {
            color: #b7c6d3;
            font-size: 0.84rem;
            line-height: 1.48;
        }
        .guide-card.top {
            border-color: rgba(255, 92, 112, 0.35);
        }
        .guide-card.bottom {
            border-color: rgba(65, 211, 138, 0.35);
        }
        .section-label {
            color: var(--muted);
            text-transform: uppercase;
            font-size: 0.72rem;
            letter-spacing: 0.08em;
            margin: 20px 0 8px 0;
        }
        .stDataFrame {
            border: 1px solid var(--line);
            border-radius: 8px;
            overflow: hidden;
        }
        div[data-testid="stRadio"] > label {
            color: var(--muted);
        }
        div[role="radiogroup"] label {
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 8px 12px;
            background: rgba(17, 24, 32, 0.66);
        }
        @media (max-width: 760px) {
            .title-row {
                align-items: flex-start;
                flex-direction: column;
            }
            .badge-row {
                justify-content: flex-start;
            }
            .guide-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=60, show_spinner=False)
def cached_load_price_data(
    ticker: str,
    period: str,
    interval: str,
    auto_adjust: bool,
) -> tuple[pd.DataFrame, str, str | None]:
    result = download_price_data(ticker, period=period, interval=interval, auto_adjust=auto_adjust)
    return result.frame, result.source, result.warning


@st.cache_data(ttl=60, show_spinner=False)
def cached_compute_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    return compute_all_indicators(frame)


def parse_watchlist(text: str) -> list[str]:
    raw = text.replace("\n", ",").split(",")
    seen: set[str] = set()
    tickers: list[str] = []
    for item in raw:
        ticker = item.strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            tickers.append(ticker)
    return tickers[:25]


def format_price(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if not math.isfinite(number):
        return "-"
    if abs(number) >= 1000:
        return f"{number:,.2f}"
    if abs(number) >= 10:
        return f"{number:.2f}"
    return f"{number:.4f}"


def format_date(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def pct_change(frame: pd.DataFrame) -> float:
    close = frame["close"].dropna()
    if len(close) < 2:
        return float("nan")
    return float((close.iloc[-1] / close.iloc[-2] - 1.0) * 100.0)


def render_header(ticker: str, source: str | None = None) -> None:
    source_badge = f"<span class='badge'>source: {source or 'pending'}</span>"
    st.markdown(
        f"""
        <div class="title-row">
            <div>
                <h1>TD DeMark Exhaustion Lab · {ticker}</h1>
                <div class="sub">Top and bottom exhaustion map with TD Combo Approx, MFI divergence, and volatility filters</div>
            </div>
            <div class="badge-row">
                <span class="badge">Yahoo Finance</span>
                <span class="badge">Educational Approx</span>
                <span class="badge">SSL verify: off</span>
                {source_badge}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="notice">
            고점 후보와 저점 후보를 모두 계산합니다. DeMARK 공식 상용 지표가 아닌 공개 규칙 기반 근사 구현이며, 현재 환경 호환성을 위해 Yahoo 요청의 SSL 검증은 우회됩니다.
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metrics(frame: pd.DataFrame, indicators: pd.DataFrame, summary: dict[str, object], source: str) -> None:
    change = pct_change(frame)
    last_date = pd.Timestamp(indicators.index[-1]).strftime("%y-%m-%d")
    columns = st.columns(5)
    columns[0].metric("Last Close", format_price(summary["close"]), f"{change:+.2f}%" if math.isfinite(change) else None)
    columns[1].metric("Active Zone", str(summary["signal_zone"]), str(summary["signal_strength"]))
    columns[2].metric("Top Score", str(summary["top_exhaustion_score"]), "고점 후보")
    columns[3].metric("Bottom Score", str(summary["bottom_exhaustion_score"]), "저점 후보")
    columns[4].metric("Last Bar", last_date, source)


def render_reading_guide() -> None:
    st.markdown("<div class='section-label'>How to read the map</div>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class="guide-grid">
            <div class="guide-card top">
                <div class="kicker">Top setup</div>
                <div class="headline">고점 후보</div>
                <div class="body">빨간 핵심 마커와 Top Score는 상승 추세가 과열되어 고점 반전 후보가 생겼다는 뜻입니다. 기본 모드는 TD와 MFI/밴드 합류 신호만 표시합니다.</div>
            </div>
            <div class="guide-card bottom">
                <div class="kicker">Bottom setup</div>
                <div class="headline">저점 후보</div>
                <div class="body">초록/시안 핵심 마커와 Bottom Score는 하락 추세가 소진되어 저점 반등 후보가 생겼다는 뜻입니다. 기본 모드는 단독 7/8 경보를 차트에 표시하지 않습니다.</div>
            </div>
            <div class="guide-card">
                <div class="kicker">Pressure</div>
                <div class="headline">리본 먼저 보기</div>
                <div class="body">빨간 리본은 고점 압력, 초록 리본은 저점 압력입니다. 리본이 높아지고 핵심 마커가 찍히면 후보 신뢰도가 올라갑니다.</div>
            </div>
            <div class="guide-card">
                <div class="kicker">Display mode</div>
                <div class="headline">Precision · Balanced · Debug</div>
                <div class="body">Precision은 강한 합류 신호만, Balanced는 9/13과 확인된 7/8, Debug는 모든 7/8/9/13 진행을 보여줍니다.</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def build_chart(
    df: pd.DataFrame,
    ticker: str,
    show_bollinger: bool,
    show_starc: bool,
    show_mfi: bool,
    display_mode: str,
) -> go.Figure:
    df = chart_frame(df)
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        row_heights=[0.64, 0.22, 0.14],
        specs=[[{}], [{}], [{}]],
    )

    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=ticker,
            increasing_line_color="#41d38a",
            increasing_fillcolor="#1f9e63",
            decreasing_line_color="#ff5c70",
            decreasing_fillcolor="#c83e51",
        ),
        row=1,
        col=1,
    )

    if show_bollinger:
        add_line(fig, df, "bb_upper", "BB Upper", "#8fa3b8", row=1)
        add_line(fig, df, "bb_middle", "BB Mid", "rgba(143,163,184,0.42)", row=1)
        add_line(fig, df, "bb_lower", "BB Lower", "#8fa3b8", row=1)
    if show_starc:
        add_line(fig, df, "starc_upper", "STARC Upper", "#f1bd4b", row=1)
        add_line(fig, df, "starc_lower", "STARC Lower", "#f1bd4b", row=1)

    marker_y_sell = df["high"] * 1.01
    marker_y_buy = df["low"] * 0.99
    add_mode_markers(fig, df, marker_y_sell, marker_y_buy, display_mode)

    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["top_pressure"],
            name="Top Pressure",
            mode="lines",
            fill="tozeroy",
            line=dict(color="#ff5c70", width=1.5),
            fillcolor="rgba(255, 92, 112, 0.20)",
        ),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=-df["bottom_pressure"],
            name="Bottom Pressure",
            mode="lines",
            fill="tozeroy",
            line=dict(color="#41d38a", width=1.5),
            fillcolor="rgba(65, 211, 138, 0.20)",
        ),
        row=2,
        col=1,
    )
    fig.add_hline(y=0, line_color="rgba(188,205,219,0.16)", row=2, col=1)

    if show_mfi:
        fig.add_trace(
            go.Scatter(x=df.index, y=df["mfi"], name="MFI", mode="lines", line=dict(color="#48b7ff", width=1.5)),
            row=3,
            col=1,
        )
        fig.add_hline(y=80, line_dash="dot", line_color="rgba(255,92,112,0.55)", row=3, col=1)
        fig.add_hline(y=20, line_dash="dot", line_color="rgba(65,211,138,0.55)", row=3, col=1)
    else:
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["bb_width"],
                name="BB Width",
                mode="lines",
                line=dict(color="rgba(241,189,75,0.82)", width=1.4),
            ),
            row=3,
            col=1,
        )

    fig.update_layout(
        height=720,
        margin=dict(l=28, r=24, t=26, b=24),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0d141c",
        font=dict(color="#dfe8ef", family="Inter, Segoe UI, sans-serif"),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="rgba(188,205,219,0.12)", zerolinecolor="rgba(188,205,219,0.12)")
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Pressure", row=2, col=1, range=[-105, 105])
    fig.update_yaxes(title_text="MFI" if show_mfi else "BB Width", row=3, col=1, range=[0, 100] if show_mfi else None)
    return fig


def chart_frame(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) <= MAX_CHART_ROWS:
        return df.copy()
    return df.tail(MAX_CHART_ROWS).copy()


def add_mode_markers(
    fig: go.Figure,
    df: pd.DataFrame,
    marker_y_sell: pd.Series,
    marker_y_buy: pd.Series,
    display_mode: str,
) -> None:
    if display_mode == "Debug":
        add_td_level_markers(fig, df, marker_y_sell, marker_y_buy)
        return

    top_mask, bottom_mask = mode_signal_masks(df, display_mode)
    add_signal_marker_trace(
        fig=fig,
        df=df,
        mask=top_mask,
        y_values=marker_y_sell * 1.015,
        event_column="top_signal_event",
        name="고점 후보 핵심",
        color="#ff5c70",
        symbol="triangle-down",
        textposition="top center",
    )
    add_signal_marker_trace(
        fig=fig,
        df=df,
        mask=bottom_mask,
        y_values=marker_y_buy * 0.985,
        event_column="bottom_signal_event",
        name="저점 후보 핵심",
        color="#41d38a",
        symbol="triangle-up",
        textposition="bottom center",
    )


def mode_signal_masks(df: pd.DataFrame, display_mode: str) -> tuple[pd.Series, pd.Series]:
    top_precision = df["top_display_signal"].astype(bool)
    bottom_precision = df["bottom_display_signal"].astype(bool)
    if display_mode == "Precision":
        return top_precision, bottom_precision

    top_confirmation = (
        df["mfi_bearish_divergence"]
        | df["bb_sell_reentry"]
        | df["starc_sell_reentry"]
        | df["td_camouflage_sell"]
    )
    bottom_confirmation = (
        df["mfi_bullish_divergence"]
        | df["bb_buy_reentry"]
        | df["starc_buy_reentry"]
        | df["td_camouflage_buy"]
    )
    top_balanced = (
        top_precision
        | first_completion(df["td_sell_setup"])
        | (df["td_sell_countdown"] == 13)
        | (df["td_sell_combo"] == 13)
        | (df["td_sell_setup"].isin([7, 8]) & top_confirmation)
    )
    bottom_balanced = (
        bottom_precision
        | first_completion(df["td_buy_setup"])
        | (df["td_buy_countdown"] == 13)
        | (df["td_buy_combo"] == 13)
        | (df["td_buy_setup"].isin([7, 8]) & bottom_confirmation)
    )
    return top_balanced.fillna(False), bottom_balanced.fillna(False)


def add_signal_marker_trace(
    fig: go.Figure,
    df: pd.DataFrame,
    mask: Iterable[bool],
    y_values: pd.Series,
    event_column: str,
    name: str,
    color: str,
    symbol: str,
    textposition: str,
) -> None:
    clean_mask = pd.Series(mask, index=df.index).fillna(False)
    points = df.loc[clean_mask].tail(MAX_SIGNAL_MARKERS)
    if points.empty:
        return
    labels = [compact_event_label(value, name) for value in points[event_column]]
    fig.add_trace(
        go.Scatter(
            x=points.index,
            y=y_values.loc[points.index],
            mode="markers+text",
            text=labels,
            textposition=textposition,
            name=name,
            marker=dict(size=13, color=color, symbol=symbol, line=dict(width=1, color="#0b0f14")),
            textfont=dict(size=10, color=color),
            hovertemplate="%{x}<br>%{text}<extra>" + name + "</extra>",
        ),
        row=1,
        col=1,
    )


def compact_event_label(value: object, fallback: str) -> str:
    text = str(value or "")
    if "Combo13" in text:
        return "C13"
    if "Countdown13" in text:
        return "D13"
    if "Setup9" in text:
        return "S9" if "고점" in fallback else "B9"
    if "MFI" in text and "Band" in text:
        return "M+B"
    if "MFI" in text:
        return "MFI"
    if "Band" in text:
        return "BAND"
    return "TOP" if "고점" in fallback else "LOW"


def add_line(fig: go.Figure, df: pd.DataFrame, column: str, name: str, color: str, row: int) -> None:
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df[column],
            name=name,
            mode="lines",
            line=dict(color=color, width=1.1),
            connectgaps=False,
        ),
        row=row,
        col=1,
    )


def first_completion(series: pd.Series) -> pd.Series:
    return (series == 9) & (series.shift(1).fillna(0) != 9)


def setup_level_mask(series: pd.Series, level: int) -> pd.Series:
    if level == 9:
        return first_completion(series)
    return series == level


def add_td_level_markers(
    fig: go.Figure,
    df: pd.DataFrame,
    marker_y_sell: pd.Series,
    marker_y_buy: pd.Series,
) -> None:
    setup_levels = (7, 8, 9)
    countdown_levels = (7, 8, 9, 13)
    combo_levels = (7, 8, 9, 13)

    for level in setup_levels:
        sell_offset = 1.000 + (level - 7) * 0.010
        buy_offset = 1.000 - (level - 7) * 0.010
        add_marker(
            fig,
            df,
            setup_level_mask(df["td_sell_setup"], level),
            marker_y_sell * sell_offset,
            f"고점 후보 Setup S{level}",
            "#ff5c70",
            "triangle-down",
            f"S{level}",
        )
        add_marker(
            fig,
            df,
            setup_level_mask(df["td_buy_setup"], level),
            marker_y_buy * buy_offset,
            f"저점 후보 Setup B{level}",
            "#41d38a",
            "triangle-up",
            f"B{level}",
        )

    for level in countdown_levels:
        sell_offset = 1.020 + (0.006 if level == 13 else (level - 7) * 0.006)
        buy_offset = 0.980 - (0.006 if level == 13 else (level - 7) * 0.006)
        add_marker(
            fig,
            df,
            df["td_sell_countdown"] == level,
            marker_y_sell * sell_offset,
            f"고점 후보 Countdown D{level}",
            "#ff8a9a",
            "x",
            f"D{level}",
        )
        add_marker(
            fig,
            df,
            df["td_buy_countdown"] == level,
            marker_y_buy * buy_offset,
            f"저점 후보 Countdown D{level}",
            "#6de0a3",
            "x",
            f"D{level}",
        )

    for level in combo_levels:
        sell_offset = 1.045 + (0.006 if level == 13 else (level - 7) * 0.006)
        buy_offset = 0.955 - (0.006 if level == 13 else (level - 7) * 0.006)
        add_marker(
            fig,
            df,
            df["td_sell_combo"] == level,
            marker_y_sell * sell_offset,
            f"고점 후보 Combo C{level}",
            "#f1bd4b",
            "diamond",
            f"C{level}",
        )
        add_marker(
            fig,
            df,
            df["td_buy_combo"] == level,
            marker_y_buy * buy_offset,
            f"저점 후보 Combo C{level}",
            "#48b7ff",
            "diamond",
            f"C{level}",
        )


def add_marker(
    fig: go.Figure,
    df: pd.DataFrame,
    mask: Iterable[bool],
    y_values: pd.Series,
    name: str,
    color: str,
    symbol: str,
    text: str,
) -> None:
    clean_mask = pd.Series(mask, index=df.index).fillna(False)
    points = df.loc[clean_mask].tail(MAX_SIGNAL_MARKERS)
    if points.empty:
        return
    fig.add_trace(
        go.Scatter(
            x=points.index,
            y=y_values.loc[points.index],
            mode="markers+text",
            text=[text] * len(points),
            textposition="top center" if ("Sell" in name or "고점" in name) else "bottom center",
            name=name,
            marker=dict(size=12, color=color, symbol=symbol, line=dict(width=1, color="#0b0f14")),
            textfont=dict(size=10, color=color),
        ),
        row=1,
        col=1,
    )


def signal_table(df: pd.DataFrame, limit: int = 80, raw: bool = False) -> pd.DataFrame:
    if raw:
        signal_mask = (
            df["display_signal"].astype(bool)
            | df["td_sell_setup"].isin([7, 8, 9])
            | df["td_buy_setup"].isin([7, 8, 9])
            | df["td_sell_countdown"].isin([7, 8, 9, 13])
            | df["td_buy_countdown"].isin([7, 8, 9, 13])
            | df["td_sell_combo"].isin([7, 8, 9, 13])
            | df["td_buy_combo"].isin([7, 8, 9, 13])
        )
    else:
        signal_mask = df["display_signal"].astype(bool)
    signals = df.loc[signal_mask, SIGNAL_COLUMNS].tail(limit).copy()
    if signals.empty:
        return pd.DataFrame(columns=["date", *SIGNAL_COLUMNS])
    signals.insert(0, "date", [format_date(index) for index in signals.index])
    signals["close"] = signals["close"].map(format_price)
    signals["mfi"] = signals["mfi"].map(lambda value: f"{value:.1f}" if pd.notna(value) else "-")
    signals["bb_width"] = signals["bb_width"].map(lambda value: f"{value:.2f}" if pd.notna(value) else "-")
    return signals.rename(
        columns={
            "signal_zone": "zone",
            "signal_side": "detail",
            "signal_quality": "quality",
            "signal_event": "event",
            "signal_strength": "strength",
            "top_exhaustion_score": "top_score",
            "bottom_exhaustion_score": "bottom_score",
            "top_pressure": "top_pressure",
            "bottom_pressure": "bottom_pressure",
        }
    )


def run_scanner(tickers: list[str], period: str, interval: str, auto_adjust: bool) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for ticker in tickers:
        try:
            frame, source, warning = cached_load_price_data(ticker, period, interval, auto_adjust)
            indicators = cached_compute_indicators(frame)
            summary = build_recent_signal_summary(indicators, lookback=SCANNER_LOOKBACK)
            rows.append(
                {
                    "ticker": ticker,
                    "close": format_price(summary["close"]),
                    "change_%": f"{pct_change(frame):+.2f}" if math.isfinite(pct_change(frame)) else "-",
                    "zone": summary["signal_zone"],
                    "quality": summary["signal_quality"] or summary["signal_strength"],
                    "days_since_signal": summary["days_since_signal"] if summary["days_since_signal"] is not None else "-",
                    "top_score": summary["top_exhaustion_score"],
                    "bottom_score": summary["bottom_exhaustion_score"],
                    "reason": summary["reason"],
                    "source": source,
                    "status": "fallback" if warning else "ok",
                    "_priority": summary["priority_score"],
                    "_recency": summary["days_since_signal"] if summary["days_since_signal"] is not None else 9999,
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "ticker": ticker,
                    "close": "-",
                    "change_%": "-",
                    "zone": "데이터 실패",
                    "quality": "없음",
                    "days_since_signal": "-",
                    "top_score": 0,
                    "bottom_score": 0,
                    "reason": "데이터 실패",
                    "source": "-",
                    "status": str(exc)[:120],
                    "_priority": 0,
                    "_recency": 9999,
                }
            )
    table = pd.DataFrame(rows)
    if not table.empty:
        table = table.sort_values(["_priority", "_recency", "top_score", "bottom_score"], ascending=[False, True, False, False])
        table = table.drop(columns=["_priority", "_recency"])
    return table


def sidebar_controls() -> tuple[str, str, str, bool, list[str], bool, bool, bool, str]:
    if "watchlist_text" not in st.session_state:
        st.session_state.watchlist_text = DEFAULT_WATCHLIST
    if "active_view" not in st.session_state:
        st.session_state.active_view = "심층 차트"

    st.sidebar.markdown("### Market")
    ticker = st.sidebar.text_input("Ticker", value=st.session_state.get("ticker", "AAPL"), key="ticker")
    period = st.sidebar.selectbox("Period", PERIOD_OPTIONS, index=2)
    interval = st.sidebar.selectbox("Interval", INTERVAL_OPTIONS, index=0)
    auto_adjust = st.sidebar.toggle("Adjusted OHLC", value=True)

    st.sidebar.markdown("### Overlays")
    display_mode = st.sidebar.selectbox("Display Mode", DISPLAY_MODES, index=0)
    show_bollinger = st.sidebar.toggle("Bollinger", value=True)
    show_starc = st.sidebar.toggle("STARC-style", value=True)
    show_mfi = st.sidebar.toggle("MFI Panel", value=True)

    st.sidebar.markdown("### Watchlist")
    watchlist_text = st.sidebar.text_area("Tickers", key="watchlist_text", height=118)
    tickers = parse_watchlist(watchlist_text)
    st.sidebar.caption(f"{len(tickers)} / 25 tickers")
    return ticker.strip().upper(), period, interval, auto_adjust, tickers, show_bollinger, show_starc, show_mfi, display_mode


def main() -> None:
    inject_css()
    (
        ticker,
        period,
        interval,
        auto_adjust,
        tickers,
        show_bollinger,
        show_starc,
        show_mfi,
        display_mode,
    ) = sidebar_controls()

    active_view = st.radio(
        "View",
        ["심층 차트", "멀티 스캐너", "신호 로그"],
        key="active_view",
        horizontal=True,
        label_visibility="collapsed",
    )

    if active_view == "멀티 스캐너":
        render_header("Scanner")
        st.markdown("<div class='section-label'>Watchlist scanner</div>", unsafe_allow_html=True)
        run_clicked = st.button("스캔 실행", type="primary")
        if run_clicked or "scan_results" not in st.session_state:
            with st.spinner("Yahoo 데이터와 TD 신호를 계산하는 중입니다."):
                st.session_state.scan_results = run_scanner(tickers, period, interval, auto_adjust)
        st.dataframe(st.session_state.scan_results, width="stretch", hide_index=True)
        return

    try:
        with st.spinner(f"{ticker} Yahoo 데이터를 불러오는 중입니다."):
            frame, source, warning = cached_load_price_data(ticker, period, interval, auto_adjust)
        indicators = cached_compute_indicators(frame)
    except DataProviderError as exc:
        render_header(ticker)
        st.error(str(exc))
        return
    except Exception as exc:
        render_header(ticker)
        st.error(f"Unexpected error: {exc}")
        return

    summary = build_signal_summary(indicators)
    render_header(ticker, source)
    if warning:
        st.warning(warning)
    render_metrics(frame, indicators, summary, source)
    render_reading_guide()

    if active_view == "신호 로그":
        st.markdown("<div class='section-label'>Signal history</div>", unsafe_allow_html=True)
        st.dataframe(signal_table(indicators, limit=220, raw=True), width="stretch", hide_index=True)
        return

    st.markdown("<div class='section-label'>Price and exhaustion map</div>", unsafe_allow_html=True)
    chart = build_chart(indicators, ticker, show_bollinger, show_starc, show_mfi, display_mode)
    st.plotly_chart(
        chart,
        width="stretch",
        config={
            "displaylogo": False,
            "scrollZoom": True,
            "modeBarButtonsToRemove": ["select2d", "lasso2d"],
        },
    )

    st.markdown("<div class='section-label'>Qualified recent signals</div>", unsafe_allow_html=True)
    st.dataframe(signal_table(indicators), width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
