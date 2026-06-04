from __future__ import annotations

import time

import numpy as np
import pandas as pd

from td_indicators import compute_all_indicators


def make_ohlcv(close: np.ndarray) -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {
            "open": close - 0.25,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(close.size, 1000.0),
        },
        index=pd.date_range("2025-01-01", periods=close.size, freq="D"),
    )


def test_td_sell_setup_and_countdowns_reach_9_and_13() -> None:
    close = np.arange(10.0, 80.0, 2.0)
    result = compute_all_indicators(make_ohlcv(close))

    first_setup_9 = result.index[result["td_sell_setup"].eq(9)][0]

    assert first_setup_9 == result.index[12]
    assert result["td_buy_setup"].max() == 0
    assert result["td_sell_countdown"].max() == 13
    assert result["td_sell_combo"].max() == 13


def test_td_buy_setup_and_countdowns_reach_9_and_13() -> None:
    close = np.arange(100.0, 30.0, -2.0)
    result = compute_all_indicators(make_ohlcv(close))

    first_setup_9 = result.index[result["td_buy_setup"].eq(9)][0]

    assert first_setup_9 == result.index[12]
    assert result["td_sell_setup"].max() == 0
    assert result["td_buy_countdown"].max() == 13
    assert result["td_buy_combo"].max() == 13


def test_indicators_tolerate_short_data_nan_and_zero_volume() -> None:
    frame = make_ohlcv(np.array([10.0, 10.5, np.nan, 11.0, 10.8, 11.2]))
    frame.loc[frame.index[:3], "volume"] = 0

    result = compute_all_indicators(frame)

    assert len(result) == len(frame)
    assert result["mfi"].dropna().between(0, 100).all()
    assert {"bb_width", "starc_upper", "starc_lower", "exhaustion_score"}.issubset(result.columns)


def test_bollinger_and_starc_exhaustion_flags() -> None:
    base = np.r_[np.full(80, 100.0), np.linspace(100.0, 130.0, 20), np.array([150.0, 103.0])]
    frame = make_ohlcv(base)
    result = compute_all_indicators(frame)

    assert result["bb_width"].notna().any()
    assert result["starc_sell_extreme"].any()
    assert result["bb_sell_reentry"].iloc[-2:].any() or result["starc_sell_reentry"].iloc[-2:].any()


def test_mfi_divergence_columns_are_boolean() -> None:
    close = np.r_[np.linspace(50, 70, 30), np.linspace(68, 76, 8), np.linspace(74, 80, 8), np.linspace(79, 72, 8)]
    frame = make_ohlcv(close)
    frame["volume"] = np.r_[np.linspace(2000, 1000, len(frame))]

    result = compute_all_indicators(frame)

    assert result["mfi"].dropna().between(0, 100).all()
    assert result["mfi_bearish_divergence"].dtype == bool
    assert result["mfi_bullish_divergence"].dtype == bool


def test_scanner_sized_indicator_computation_is_fast_enough() -> None:
    close = 100 + np.cumsum(np.sin(np.arange(504) / 7.0) + 0.15)
    frames = [make_ohlcv(close + i) for i in range(25)]

    start = time.perf_counter()
    for frame in frames:
        compute_all_indicators(frame)
    elapsed = time.perf_counter() - start

    assert elapsed < 5.0
