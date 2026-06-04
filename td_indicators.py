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
    sell_perfected = (
        (df["td_sell_setup"] == 9)
        & (
            (high >= high.shift(2))
            | (high >= high.shift(3))
            | (high.shift(1) >= high.shift(2))
            | (high.shift(1) >= high.shift(3))
        )
    )
    buy_perfected = (
        (df["td_buy_setup"] == 9)
        & (
            (low <= low.shift(2))
            | (low <= low.shift(3))
            | (low.shift(1) <= low.shift(2))
            | (low.shift(1) <= low.shift(3))
        )
    )
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

    buy_active = False
    sell_active = False
    buy_count = 0
    sell_count = 0

    for i in range(size):
        previous_sell_setup = sell_setup[i - 1] if i > 0 else 0
        previous_buy_setup = buy_setup[i - 1] if i > 0 else 0
        sell_setup_completed = sell_setup[i] == 9 and previous_sell_setup != 9
        buy_setup_completed = buy_setup[i] == 9 and previous_buy_setup != 9

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

        if i < 2 or not np.isfinite(close[i]):
            continue

        if sell_active and np.isfinite(high[i - 2]) and close[i] >= high[i - 2]:
            sell_count += 1
            sell[i] = sell_count
            if sell_count >= 13:
                sell_active = False
                sell_count = 0

        if buy_active and np.isfinite(low[i - 2]) and close[i] <= low[i - 2]:
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

    buy_count = 0
    sell_count = 0
    last_buy_close = np.nan
    last_sell_close = np.nan

    for i in range(size):
        if sell_setup[i] > 0:
            buy_count = 0
            last_buy_close = np.nan
        if buy_setup[i] > 0:
            sell_count = 0
            last_sell_close = np.nan

        if i < 4 or not np.isfinite(close[i]):
            continue

        sell_ok = (
            sell_setup[i] > 0
            and i >= 2
            and np.isfinite(high[i - 2])
            and close[i] >= high[i - 2]
            and np.isfinite(close[i - 1])
            and close[i] >= close[i - 1]
            and (not np.isfinite(last_sell_close) or close[i] > last_sell_close)
        )
        if sell_ok:
            sell_count += 1
            sell[i] = sell_count
            last_sell_close = close[i]
            if sell_count >= 13:
                sell_count = 0
                last_sell_close = np.nan

        buy_ok = (
            buy_setup[i] > 0
            and i >= 2
            and np.isfinite(low[i - 2])
            and close[i] <= low[i - 2]
            and np.isfinite(close[i - 1])
            and close[i] <= close[i - 1]
            and (not np.isfinite(last_buy_close) or close[i] < last_buy_close)
        )
        if buy_ok:
            buy_count += 1
            buy[i] = buy_count
            last_buy_close = close[i]
            if buy_count >= 13:
                buy_count = 0
                last_buy_close = np.nan

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
    high_pivots: list[int] = []
    low_pivots: list[int] = []

    for i in range(lookback, size - lookback):
        window_high = high[i - lookback : i + lookback + 1]
        window_low = low[i - lookback : i + lookback + 1]
        if not np.isfinite(oscillator[i]):
            continue

        if np.isfinite(high[i]) and high[i] == np.nanmax(window_high):
            if high_pivots:
                previous = high_pivots[-1]
                if high[i] > high[previous] and oscillator[i] < oscillator[previous]:
                    bearish[i] = True
            high_pivots.append(i)

        if np.isfinite(low[i]) and low[i] == np.nanmin(window_low):
            if low_pivots:
                previous = low_pivots[-1]
                if low[i] < low[previous] and oscillator[i] > oscillator[previous]:
                    bullish[i] = True
            low_pivots.append(i)

    return bearish, bullish


def add_signal_scores(df: pd.DataFrame) -> None:
    sell_score = (
        (df["td_sell_setup"] == 9).astype(int)
        + (df["td_sell_perfected"]).astype(int)
        + 3 * (df["td_sell_countdown"] == 13).astype(int)
        + 4 * (df["td_sell_combo"] == 13).astype(int)
        + 2 * df["mfi_bearish_divergence"].astype(int)
        + 2 * df["bb_sell_reentry"].astype(int)
        + df["starc_sell_extreme"].astype(int)
        + 2 * df["starc_sell_reentry"].astype(int)
        + df["td_camouflage_sell"].astype(int)
    )
    buy_score = (
        (df["td_buy_setup"] == 9).astype(int)
        + (df["td_buy_perfected"]).astype(int)
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


def build_signal_summary(df: pd.DataFrame) -> dict[str, object]:
    if df.empty:
        return {
            "close": np.nan,
            "signal_side": "데이터 없음",
            "signal_zone": "데이터 없음",
            "signal_strength": "없음",
            "bearish_exhaustion_score": 0,
            "bullish_exhaustion_score": 0,
            "top_exhaustion_score": 0,
            "bottom_exhaustion_score": 0,
            "last_signal_at": None,
        }

    latest = df.iloc[-1]
    signal_mask = (
        (df["bearish_exhaustion_score"] > 0)
        | (df["bullish_exhaustion_score"] > 0)
        | (df["td_sell_countdown"] == 13)
        | (df["td_buy_countdown"] == 13)
        | (df["td_sell_combo"] == 13)
        | (df["td_buy_combo"] == 13)
    )
    signal_rows = df.loc[signal_mask]
    last_signal_at = signal_rows.index[-1] if not signal_rows.empty else None

    return {
        "close": float(latest["close"]) if pd.notna(latest["close"]) else np.nan,
        "signal_side": str(latest["signal_side"]),
        "signal_zone": str(latest["signal_zone"]),
        "signal_strength": str(latest["signal_strength"]),
        "bearish_exhaustion_score": int(latest["bearish_exhaustion_score"]),
        "bullish_exhaustion_score": int(latest["bullish_exhaustion_score"]),
        "top_exhaustion_score": int(latest["top_exhaustion_score"]),
        "bottom_exhaustion_score": int(latest["bottom_exhaustion_score"]),
        "td_sell_setup": int(latest["td_sell_setup"]),
        "td_buy_setup": int(latest["td_buy_setup"]),
        "td_sell_countdown": int(latest["td_sell_countdown"]),
        "td_buy_countdown": int(latest["td_buy_countdown"]),
        "td_sell_combo": int(latest["td_sell_combo"]),
        "td_buy_combo": int(latest["td_buy_combo"]),
        "last_signal_at": last_signal_at,
    }
