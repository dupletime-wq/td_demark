from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class IndicatorParams:
    mfi_period: int = 14
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    squeeze_window: int = 120
    squeeze_quantile: float = 0.15
    atr_period: int = 14
    starc_period: int = 20
    starc_multiplier: float = 2.0
    pivot_lookback: int = 5


def compute_all_indicators(
    frame: pd.DataFrame,
    params: IndicatorParams | None = None,
) -> pd.DataFrame:
    params = params or IndicatorParams()
    df = prepare_ohlcv(frame)

    add_td_setup(df)
    add_td_countdowns(df)
    add_money_flow_index(df, params.mfi_period)
    add_bollinger(df, params.bollinger_period, params.bollinger_std, params.squeeze_window, params.squeeze_quantile)
    add_starc(df, params.starc_period, params.atr_period, params.starc_multiplier)
    add_divergences(df, params.pivot_lookback)
    add_signal_scores(df)

    return df


def prepare_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    required = ("open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {', '.join(missing)}")

    df = frame.copy().sort_index()
    for column in required:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["volume"] = df["volume"].fillna(0)
    return df


def add_td_setup(df: pd.DataFrame) -> None:
    close = df["close"]
    sell_condition = close > close.shift(4)
    buy_condition = close < close.shift(4)

    df["td_sell_setup"] = consecutive_count(sell_condition, cap=9)
    df["td_buy_setup"] = consecutive_count(buy_condition, cap=9)

    high = df["high"]
    low = df["low"]
    # Perfection requires the high of bar 8 OR bar 9 to exceed BOTH bar 6 and bar 7
    # (not just any one of the four pairwise comparisons).
    bar9_exceeds_both = (high >= high.shift(2)) & (high >= high.shift(3))
    bar8_exceeds_both = (high.shift(1) >= high.shift(2)) & (high.shift(1) >= high.shift(3))
    sell_perfected = (df["td_sell_setup"] == 9) & (bar9_exceeds_both | bar8_exceeds_both)

    bar9_below_both = (low <= low.shift(2)) & (low <= low.shift(3))
    bar8_below_both = (low.shift(1) <= low.shift(2)) & (low.shift(1) <= low.shift(3))
    buy_perfected = (df["td_buy_setup"] == 9) & (bar9_below_both | bar8_below_both)
    df["td_sell_perfected"] = sell_perfected.fillna(False)
    df["td_buy_perfected"] = buy_perfected.fillna(False)


def consecutive_count(mask: pd.Series, cap: int) -> pd.Series:
    clean = mask.fillna(False)
    groups = (~clean).cumsum()
    counts = clean.astype("int16").groupby(groups).cumsum().clip(upper=cap)
    return counts.astype("int16")


def add_td_countdowns(df: pd.DataFrame) -> None:
    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    buy_setup = df["td_buy_setup"].to_numpy(dtype=np.int16)
    sell_setup = df["td_sell_setup"].to_numpy(dtype=np.int16)

    buy_cd, sell_cd = sequential_countdown(close, high, low, buy_setup, sell_setup)
    buy_combo, sell_combo = combo_countdown(close, high, low, buy_setup, sell_setup)

    df["td_buy_countdown"] = buy_cd
    df["td_sell_countdown"] = sell_cd
    df["td_buy_combo"] = buy_combo
    df["td_sell_combo"] = sell_combo


def sequential_countdown(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    buy_setup: np.ndarray,
    sell_setup: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    size = close.size
    buy = np.zeros(size, dtype=np.int16)
    sell = np.zeros(size, dtype=np.int16)

    # Plain Python lists avoid per-element NumPy scalar boxing/np.isfinite call overhead
    # in this tight, inherently sequential (state-carrying) loop.
    close_l = close.tolist()
    high_finite = np.isfinite(high)
    low_finite = np.isfinite(low)
    close_finite = np.isfinite(close).tolist()
    high_l = high.tolist()
    low_l = low.tolist()
    high_finite_l = high_finite.tolist()
    low_finite_l = low_finite.tolist()
    buy_setup_l = buy_setup.tolist()
    sell_setup_l = sell_setup.tolist()

    buy_active = False
    sell_active = False
    buy_count = 0
    sell_count = 0
    previous_sell_setup = 0
    previous_buy_setup = 0

    for i in range(size):
        current_sell_setup = sell_setup_l[i]
        current_buy_setup = buy_setup_l[i]
        sell_setup_completed = current_sell_setup == 9 and previous_sell_setup != 9
        buy_setup_completed = current_buy_setup == 9 and previous_buy_setup != 9
        previous_sell_setup = current_sell_setup
        previous_buy_setup = current_buy_setup

        if sell_setup_completed:
            sell_active = True
            buy_active = False
            sell_count = 0
            buy_count = 0
        elif buy_setup_completed:
            buy_active = True
            sell_active = False
            buy_count = 0
            sell_count = 0

        if i < 2 or not close_finite[i]:
            continue

        if sell_active and high_finite_l[i - 2] and close_l[i] >= high_l[i - 2]:
            sell_count += 1
            sell[i] = sell_count
            if sell_count >= 13:
                sell_active = False
                sell_count = 0

        if buy_active and low_finite_l[i - 2] and close_l[i] <= low_l[i - 2]:
            buy_count += 1
            buy[i] = buy_count
            if buy_count >= 13:
                buy_active = False
                buy_count = 0

    return buy, sell


def combo_countdown(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    buy_setup: np.ndarray,
    sell_setup: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    size = close.size
    buy = np.zeros(size, dtype=np.int16)
    sell = np.zeros(size, dtype=np.int16)

    # Same rationale as sequential_countdown: plain Python lists and precomputed
    # finite-masks remove per-element NumPy overhead from this sequential loop.
    close_l = close.tolist()
    high_l = high.tolist()
    low_l = low.tolist()
    close_finite_l = np.isfinite(close).tolist()
    high_finite_l = np.isfinite(high).tolist()
    low_finite_l = np.isfinite(low).tolist()
    buy_setup_l = buy_setup.tolist()
    sell_setup_l = sell_setup.tolist()

    buy_count = 0
    sell_count = 0
    last_buy_close: float | None = None
    last_sell_close: float | None = None

    for i in range(size):
        if sell_setup_l[i] > 0:
            buy_count = 0
            last_buy_close = None
        if buy_setup_l[i] > 0:
            sell_count = 0
            last_sell_close = None

        if i < 4 or not close_finite_l[i]:
            continue

        close_i = close_l[i]
        sell_ok = (
            sell_setup_l[i] > 0
            and high_finite_l[i - 2]
            and close_i >= high_l[i - 2]
            and close_finite_l[i - 1]
            and close_i >= close_l[i - 1]
            and (last_sell_close is None or close_i > last_sell_close)
        )
        if sell_ok:
            sell_count += 1
            sell[i] = sell_count
            last_sell_close = close_i
            if sell_count >= 13:
                sell_count = 0
                last_sell_close = None

        buy_ok = (
            buy_setup_l[i] > 0
            and low_finite_l[i - 2]
            and close_i <= low_l[i - 2]
            and close_finite_l[i - 1]
            and close_i <= close_l[i - 1]
            and (last_buy_close is None or close_i < last_buy_close)
        )
        if buy_ok:
            buy_count += 1
            buy[i] = buy_count
            last_buy_close = close_i
            if buy_count >= 13:
                buy_count = 0
                last_buy_close = None

    return buy, sell


def add_money_flow_index(df: pd.DataFrame, period: int) -> None:
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    money_flow = typical * df["volume"].clip(lower=0)
    direction = typical.diff()

    positive = money_flow.where(direction > 0, 0.0)
    negative = money_flow.where(direction < 0, 0.0).abs()

    positive_sum = positive.rolling(period, min_periods=period).sum()
    negative_sum = negative.rolling(period, min_periods=period).sum()
    denominator = positive_sum + negative_sum

    mfi = np.where(
        denominator > 0,
        100.0 * positive_sum / denominator,
        np.where(positive_sum > 0, 100.0, 50.0),
    )
    df["mfi"] = pd.Series(mfi, index=df.index).clip(0, 100)


def add_bollinger(
    df: pd.DataFrame,
    period: int,
    std_multiplier: float,
    squeeze_window: int,
    squeeze_quantile: float,
) -> None:
    close = df["close"]
    middle = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std(ddof=0)
    upper = middle + std_multiplier * std
    lower = middle - std_multiplier * std
    width = ((upper - lower) / middle.replace(0, np.nan)).abs() * 100.0
    threshold = width.rolling(squeeze_window, min_periods=min(40, squeeze_window)).quantile(squeeze_quantile)
    squeeze = width <= threshold
    recent_squeeze = squeeze.shift(1).rolling(8, min_periods=1).max().fillna(0).astype(bool)
    release = recent_squeeze & (width > width.shift(1)) & ((close > upper) | (close < lower))

    df["bb_middle"] = middle
    df["bb_upper"] = upper
    df["bb_lower"] = lower
    df["bb_width"] = width
    df["bb_squeeze"] = squeeze.fillna(False)
    df["bb_release"] = release.fillna(False)
    df["bb_sell_reentry"] = ((close.shift(1) > upper.shift(1)) & (close <= upper)).fillna(False)
    df["bb_buy_reentry"] = ((close.shift(1) < lower.shift(1)) & (close >= lower)).fillna(False)


def add_starc(df: pd.DataFrame, starc_period: int, atr_period: int, multiplier: float) -> None:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.rolling(atr_period, min_periods=atr_period).mean()
    basis = close.ewm(span=starc_period, adjust=False, min_periods=starc_period).mean()

    upper = basis + multiplier * atr
    lower = basis - multiplier * atr
    df["atr"] = atr
    df["starc_basis"] = basis
    df["starc_upper"] = upper
    df["starc_lower"] = lower
    df["starc_sell_extreme"] = (close > upper).fillna(False)
    df["starc_buy_extreme"] = (close < lower).fillna(False)
    df["starc_sell_reentry"] = ((close.shift(1) > upper.shift(1)) & (close <= upper)).fillna(False)
    df["starc_buy_reentry"] = ((close.shift(1) < lower.shift(1)) & (close >= lower)).fillna(False)


def add_divergences(df: pd.DataFrame, lookback: int) -> None:
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    open_ = df["open"].to_numpy(dtype=float)
    mfi = df["mfi"].to_numpy(dtype=float)

    bearish, bullish = pivot_divergence(high, low, mfi, lookback)
    camouflage_sell = (
        (close > open_)
        & (high > np.roll(high, 1))
        & (mfi < np.roll(mfi, 1))
    )
    camouflage_buy = (
        (close < open_)
        & (low < np.roll(low, 1))
        & (mfi > np.roll(mfi, 1))
    )
    if camouflage_sell.size:
        camouflage_sell[0] = False
        camouflage_buy[0] = False

    df["mfi_bearish_divergence"] = bearish
    df["mfi_bullish_divergence"] = bullish
    df["td_camouflage_sell"] = np.nan_to_num(camouflage_sell, nan=False).astype(bool)
    df["td_camouflage_buy"] = np.nan_to_num(camouflage_buy, nan=False).astype(bool)


def pivot_divergence(
    high: np.ndarray,
    low: np.ndarray,
    oscillator: np.ndarray,
    lookback: int,
) -> tuple[np.ndarray, np.ndarray]:
    size = high.size
    bearish = np.zeros(size, dtype=bool)
    bullish = np.zeros(size, dtype=bool)
    if size <= 2 * lookback:
        return bearish, bullish

    # A centered rolling max/min (via pandas' O(n) monotonic-window algorithm) replaces
    # the previous per-row np.nanmax/np.nanmin over a re-sliced window, which was the
    # dominant cost of this function on longer price histories.
    window = 2 * lookback + 1
    rolling_high_max = pd.Series(high).rolling(window, center=True, min_periods=1).max().to_numpy()
    rolling_low_min = pd.Series(low).rolling(window, center=True, min_periods=1).min().to_numpy()

    finite_oscillator = np.isfinite(oscillator)
    is_high_pivot = np.isfinite(high) & finite_oscillator & (high == rolling_high_max)
    is_low_pivot = np.isfinite(low) & finite_oscillator & (low == rolling_low_min)
    is_high_pivot[:lookback] = False
    is_high_pivot[size - lookback :] = False
    is_low_pivot[:lookback] = False
    is_low_pivot[size - lookback :] = False

    high_pivots = np.flatnonzero(is_high_pivot)
    for pos in range(1, high_pivots.size):
        i = high_pivots[pos]
        previous = high_pivots[pos - 1]
        if high[i] > high[previous] and oscillator[i] < oscillator[previous]:
            bearish[i] = True

    low_pivots = np.flatnonzero(is_low_pivot)
    for pos in range(1, low_pivots.size):
        i = low_pivots[pos]
        previous = low_pivots[pos - 1]
        if low[i] < low[previous] and oscillator[i] > oscillator[previous]:
            bullish[i] = True

    return bearish, bullish


def add_signal_scores(df: pd.DataFrame) -> None:
    sell_setup_event = first_setup_event(df["td_sell_setup"])
    buy_setup_event = first_setup_event(df["td_buy_setup"])
    sell_td_13 = (df["td_sell_countdown"] == 13) | (df["td_sell_combo"] == 13)
    buy_td_13 = (df["td_buy_countdown"] == 13) | (df["td_buy_combo"] == 13)
    sell_td_core = sell_setup_event | sell_td_13
    buy_td_core = buy_setup_event | buy_td_13
    sell_mfi = df["mfi_bearish_divergence"] | df["td_camouflage_sell"]
    buy_mfi = df["mfi_bullish_divergence"] | df["td_camouflage_buy"]
    sell_band = df["bb_sell_reentry"] | df["starc_sell_reentry"]
    buy_band = df["bb_buy_reentry"] | df["starc_buy_reentry"]

    sell_score = (
        2 * sell_setup_event.astype(int)
        + (df["td_sell_perfected"] & sell_setup_event).astype(int)
        + 3 * (df["td_sell_countdown"] == 13).astype(int)
        + 4 * (df["td_sell_combo"] == 13).astype(int)
        + 2 * df["mfi_bearish_divergence"].astype(int)
        + 2 * df["bb_sell_reentry"].astype(int)
        + df["starc_sell_extreme"].astype(int)
        + 2 * df["starc_sell_reentry"].astype(int)
        + df["td_camouflage_sell"].astype(int)
    )
    buy_score = (
        2 * buy_setup_event.astype(int)
        + (df["td_buy_perfected"] & buy_setup_event).astype(int)
        + 3 * (df["td_buy_countdown"] == 13).astype(int)
        + 4 * (df["td_buy_combo"] == 13).astype(int)
        + 2 * df["mfi_bullish_divergence"].astype(int)
        + 2 * df["bb_buy_reentry"].astype(int)
        + df["starc_buy_extreme"].astype(int)
        + 2 * df["starc_buy_reentry"].astype(int)
        + df["td_camouflage_buy"].astype(int)
    )
    df["bearish_exhaustion_score"] = sell_score.astype("int16")
    df["bullish_exhaustion_score"] = buy_score.astype("int16")
    df["top_exhaustion_score"] = df["bearish_exhaustion_score"]
    df["bottom_exhaustion_score"] = df["bullish_exhaustion_score"]
    df["exhaustion_score"] = sell_score - buy_score
    df["top_pressure"] = compute_pressure(
        setup=df["td_sell_setup"],
        countdown=df["td_sell_countdown"],
        combo=df["td_sell_combo"],
        mfi=sell_mfi,
        band=sell_band,
        extreme=df["starc_sell_extreme"],
    )
    df["bottom_pressure"] = compute_pressure(
        setup=df["td_buy_setup"],
        countdown=df["td_buy_countdown"],
        combo=df["td_buy_combo"],
        mfi=buy_mfi,
        band=buy_band,
        extreme=df["starc_buy_extreme"],
    )

    top_has_confirmation = sell_mfi | sell_band
    bottom_has_confirmation = buy_mfi | buy_band
    top_display = ((sell_score >= 3) & sell_td_core & top_has_confirmation) | sell_td_13
    bottom_display = ((buy_score >= 3) & buy_td_core & bottom_has_confirmation) | buy_td_13
    df["top_display_signal"] = top_display.fillna(False)
    df["bottom_display_signal"] = bottom_display.fillna(False)
    df["display_signal"] = df["top_display_signal"] | df["bottom_display_signal"]
    df["top_signal_event"] = build_event_labels(
        setup_event=sell_setup_event,
        countdown=df["td_sell_countdown"],
        combo=df["td_sell_combo"],
        mfi=sell_mfi,
        band=sell_band,
        display=df["top_display_signal"],
        prefix="Top",
    )
    df["bottom_signal_event"] = build_event_labels(
        setup_event=buy_setup_event,
        countdown=df["td_buy_countdown"],
        combo=df["td_buy_combo"],
        mfi=buy_mfi,
        band=buy_band,
        display=df["bottom_display_signal"],
        prefix="Bottom",
    )
    df["top_signal_quality"] = score_quality(sell_score, df["top_display_signal"])
    df["bottom_signal_quality"] = score_quality(buy_score, df["bottom_display_signal"])

    df["signal_zone"] = np.select(
        [
            sell_score > buy_score,
            buy_score > sell_score,
        ],
        [
            "고점 후보",
            "저점 후보",
        ],
        default="중립",
    )
    df["signal_side"] = np.select(
        [
            sell_score > buy_score,
            buy_score > sell_score,
        ],
        [
            "상승 추세 소진 -> 고점 후보",
            "하락 추세 소진 -> 저점 후보",
        ],
        default="중립",
    )
    max_score = np.maximum(sell_score, buy_score)
    df["signal_strength"] = np.select(
        [
            max_score >= 6,
            max_score >= 3,
            max_score >= 1,
        ],
        [
            "강함",
            "주의",
            "관찰",
        ],
        default="없음",
    )
    top_active = df["top_display_signal"] & (sell_score >= buy_score)
    bottom_active = df["bottom_display_signal"] & (buy_score > sell_score)
    df["signal_event"] = np.select(
        [top_active, bottom_active, df["top_display_signal"], df["bottom_display_signal"]],
        [df["top_signal_event"], df["bottom_signal_event"], df["top_signal_event"], df["bottom_signal_event"]],
        default="",
    )
    df["signal_quality"] = np.select(
        [top_active, bottom_active, df["top_display_signal"], df["bottom_display_signal"]],
        [df["top_signal_quality"], df["bottom_signal_quality"], df["top_signal_quality"], df["bottom_signal_quality"]],
        default="",
    )


def first_setup_event(series: pd.Series) -> pd.Series:
    return (series == 9) & (series.shift(1).fillna(0) != 9)


def compute_pressure(
    setup: pd.Series,
    countdown: pd.Series,
    combo: pd.Series,
    mfi: pd.Series,
    band: pd.Series,
    extreme: pd.Series,
) -> pd.Series:
    # NumPy arithmetic replaces the previous per-column pandas Series ops + pd.concat,
    # which dominated add_signal_scores's runtime (each pandas op re-wraps a Series).
    setup_part = np.clip(setup.to_numpy(dtype=float), 0, 9) / 9.0 * 35.0
    countdown_part = np.clip(countdown.to_numpy(dtype=float), 0, 13) / 13.0 * 65.0
    combo_part = np.clip(combo.to_numpy(dtype=float), 0, 13) / 13.0 * 75.0
    base = np.maximum(np.maximum(setup_part, countdown_part), combo_part)
    base = pd.Series(base, index=setup.index).rolling(5, min_periods=1).max().to_numpy()
    confirmation = (
        12.0 * mfi.to_numpy(dtype=float)
        + 12.0 * band.to_numpy(dtype=float)
        + 6.0 * extreme.to_numpy(dtype=float)
    )
    result = np.clip(base + confirmation, 0, 100)
    return pd.Series(result, index=setup.index)


def score_quality(score: pd.Series, display: pd.Series) -> pd.Series:
    return pd.Series(
        np.select(
            [
                display & (score >= 6),
                display & (score >= 3),
                display,
            ],
            [
                "강함",
                "주의",
                "관찰",
            ],
            default="",
        ),
        index=score.index,
    )


def build_event_labels(
    setup_event: pd.Series,
    countdown: pd.Series,
    combo: pd.Series,
    mfi: pd.Series,
    band: pd.Series,
    display: pd.Series,
    prefix: str,
) -> pd.Series:
    labels: list[str] = []
    for setup_ok, countdown_value, combo_value, mfi_ok, band_ok, display_ok in zip(
        setup_event.to_numpy(dtype=bool),
        countdown.to_numpy(dtype=np.int16),
        combo.to_numpy(dtype=np.int16),
        mfi.to_numpy(dtype=bool),
        band.to_numpy(dtype=bool),
        display.to_numpy(dtype=bool),
    ):
        if not display_ok:
            labels.append("")
            continue

        parts: list[str] = []
        if combo_value == 13:
            parts.append("Combo13")
        if countdown_value == 13:
            parts.append("Countdown13")
        if setup_ok:
            parts.append("Setup9")
        if mfi_ok:
            parts.append("MFI")
        if band_ok:
            parts.append("Band")
        labels.append(f"{prefix}: " + "+".join(parts) if parts else prefix)
    return pd.Series(labels, index=display.index)


def build_signal_summary(df: pd.DataFrame) -> dict[str, object]:
    if df.empty:
        return {
            "close": np.nan,
            "signal_side": "데이터 없음",
            "signal_zone": "데이터 없음",
            "signal_strength": "없음",
            "signal_event": "",
            "signal_quality": "",
            "bearish_exhaustion_score": 0,
            "bullish_exhaustion_score": 0,
            "top_exhaustion_score": 0,
            "bottom_exhaustion_score": 0,
            "top_pressure": 0.0,
            "bottom_pressure": 0.0,
            "display_signal": False,
            "last_signal_at": None,
        }

    latest = df.iloc[-1]
    signal_mask = df["display_signal"].astype(bool)
    signal_rows = df.loc[signal_mask]
    last_signal_at = signal_rows.index[-1] if not signal_rows.empty else None

    return {
        "close": float(latest["close"]) if pd.notna(latest["close"]) else np.nan,
        "signal_side": str(latest["signal_side"]),
        "signal_zone": str(latest["signal_zone"]),
        "signal_strength": str(latest["signal_strength"]),
        "signal_event": str(latest["signal_event"]),
        "signal_quality": str(latest["signal_quality"]),
        "bearish_exhaustion_score": int(latest["bearish_exhaustion_score"]),
        "bullish_exhaustion_score": int(latest["bullish_exhaustion_score"]),
        "top_exhaustion_score": int(latest["top_exhaustion_score"]),
        "bottom_exhaustion_score": int(latest["bottom_exhaustion_score"]),
        "top_pressure": float(latest["top_pressure"]) if pd.notna(latest["top_pressure"]) else 0.0,
        "bottom_pressure": float(latest["bottom_pressure"]) if pd.notna(latest["bottom_pressure"]) else 0.0,
        "display_signal": bool(latest["display_signal"]),
        "td_sell_setup": int(latest["td_sell_setup"]),
        "td_buy_setup": int(latest["td_buy_setup"]),
        "td_sell_countdown": int(latest["td_sell_countdown"]),
        "td_buy_countdown": int(latest["td_buy_countdown"]),
        "td_sell_combo": int(latest["td_sell_combo"]),
        "td_buy_combo": int(latest["td_buy_combo"]),
        "last_signal_at": last_signal_at,
    }


def build_recent_signal_summary(df: pd.DataFrame, lookback: int = 20) -> dict[str, object]:
    latest_summary = build_signal_summary(df)
    if df.empty:
        return latest_summary | {
            "qualified_at": None,
            "days_since_signal": None,
            "reason": "",
            "priority_score": 0,
        }

    recent = df.tail(lookback).copy()
    qualified = recent.loc[recent["display_signal"].astype(bool)]
    if qualified.empty:
        return latest_summary | {
            "qualified_at": None,
            "days_since_signal": None,
            "reason": "최근 강한 합류 신호 없음",
            "priority_score": 0,
        }

    qualified = qualified.assign(
        _priority_score=np.maximum(
            qualified["top_exhaustion_score"].to_numpy(dtype=float),
            qualified["bottom_exhaustion_score"].to_numpy(dtype=float),
        )
    )
    best = qualified.sort_values(["_priority_score"], ascending=False).iloc[0]
    latest_index = pd.Timestamp(df.index[-1])
    signal_index = pd.Timestamp(best.name)
    days_since = max((latest_index - signal_index).days, 0)

    return {
        "close": float(df.iloc[-1]["close"]) if pd.notna(df.iloc[-1]["close"]) else np.nan,
        "signal_side": str(best["signal_side"]),
        "signal_zone": str(best["signal_zone"]),
        "signal_strength": str(best["signal_strength"]),
        "signal_event": str(best["signal_event"]),
        "signal_quality": str(best["signal_quality"]),
        "bearish_exhaustion_score": int(best["bearish_exhaustion_score"]),
        "bullish_exhaustion_score": int(best["bullish_exhaustion_score"]),
        "top_exhaustion_score": int(best["top_exhaustion_score"]),
        "bottom_exhaustion_score": int(best["bottom_exhaustion_score"]),
        "top_pressure": float(df.iloc[-1]["top_pressure"]) if pd.notna(df.iloc[-1]["top_pressure"]) else 0.0,
        "bottom_pressure": float(df.iloc[-1]["bottom_pressure"]) if pd.notna(df.iloc[-1]["bottom_pressure"]) else 0.0,
        "display_signal": bool(best["display_signal"]),
        "td_sell_setup": int(df.iloc[-1]["td_sell_setup"]),
        "td_buy_setup": int(df.iloc[-1]["td_buy_setup"]),
        "td_sell_countdown": int(df.iloc[-1]["td_sell_countdown"]),
        "td_buy_countdown": int(df.iloc[-1]["td_buy_countdown"]),
        "td_sell_combo": int(df.iloc[-1]["td_sell_combo"]),
        "td_buy_combo": int(df.iloc[-1]["td_buy_combo"]),
        "last_signal_at": latest_summary["last_signal_at"],
        "qualified_at": best.name,
        "days_since_signal": days_since,
        "reason": str(best["signal_event"]),
        "priority_score": int(best["_priority_score"]),
    }
