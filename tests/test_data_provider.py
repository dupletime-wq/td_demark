from __future__ import annotations

import pandas as pd
import pytest

import data_provider
from data_provider import DataProviderError, download_price_data, normalize_price_frame, parse_raw_chart_response


def test_normalize_yfinance_multiindex_field_first() -> None:
    columns = pd.MultiIndex.from_tuples(
        [
            ("Open", "AAPL"),
            ("High", "AAPL"),
            ("Low", "AAPL"),
            ("Close", "AAPL"),
            ("Volume", "AAPL"),
        ]
    )
    frame = pd.DataFrame(
        [[10, 12, 9, 11, 1000], [11, 13, 10, 12, 1200]],
        index=pd.date_range("2026-01-01", periods=2),
        columns=columns,
    )

    normalized = normalize_price_frame(frame, "AAPL")

    assert list(normalized.columns) == ["open", "high", "low", "close", "volume"]
    assert normalized["close"].iloc[-1] == 12


def test_normalize_yfinance_multiindex_ticker_first() -> None:
    columns = pd.MultiIndex.from_tuples(
        [
            ("MSFT", "Open"),
            ("MSFT", "High"),
            ("MSFT", "Low"),
            ("MSFT", "Close"),
            ("MSFT", "Volume"),
        ]
    )
    frame = pd.DataFrame(
        [[20, 22, 19, 21, 2000]],
        index=pd.date_range("2026-01-01", periods=1),
        columns=columns,
    )

    normalized = normalize_price_frame(frame, "MSFT")

    assert normalized.loc[normalized.index[0], "open"] == 20
    assert normalized.loc[normalized.index[0], "volume"] == 2000


def test_parse_raw_chart_response_adjusts_ohlc_with_adj_close() -> None:
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1_704_067_200, 1_704_153_600],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0, 110.0],
                                "high": [105.0, 115.0],
                                "low": [95.0, 105.0],
                                "close": [100.0, 110.0],
                                "volume": [1000, 1200],
                            }
                        ],
                        "adjclose": [{"adjclose": [50.0, 55.0]}],
                    },
                }
            ],
            "error": None,
        }
    }

    frame = parse_raw_chart_response("AAPL", payload, auto_adjust=True)

    assert frame["close"].tolist() == [50.0, 55.0]
    assert frame["open"].tolist() == [50.0, 55.0]
    assert frame["volume"].tolist() == [1000, 1200]


def test_download_falls_back_to_raw_chart(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = pd.DataFrame(
        {
            "open": [1.0],
            "high": [2.0],
            "low": [0.5],
            "close": [1.5],
            "volume": [100],
        },
        index=pd.date_range("2026-01-01", periods=1),
    )

    def fail_yfinance(*args: object, **kwargs: object) -> pd.DataFrame:
        raise DataProviderError("primary failed")

    def ok_raw(*args: object, **kwargs: object) -> pd.DataFrame:
        return raw

    monkeypatch.setattr(data_provider, "fetch_yfinance", fail_yfinance)
    monkeypatch.setattr(data_provider, "fetch_raw_chart", ok_raw)

    result = download_price_data("aapl")

    assert result.source == "yahoo_chart_api"
    assert result.warning and "primary failed" in result.warning
    assert result.frame["close"].iloc[0] == 1.5
