from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import yfinance as yf
from curl_cffi import requests


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


class DataProviderError(RuntimeError):
    """Raised when Yahoo data cannot be fetched or normalized."""


@dataclass(frozen=True)
class PriceDataResult:
    frame: pd.DataFrame
    source: str
    warning: str | None = None


def make_yahoo_session() -> requests.Session:
    return requests.Session(impersonate="chrome", verify=False)


def download_price_data(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
    auto_adjust: bool = True,
    timeout: int = 20,
) -> PriceDataResult:
    normalized = normalize_ticker(ticker)
    if not normalized:
        raise DataProviderError("Ticker is empty.")

    try:
        frame = fetch_yfinance(normalized, period, interval, auto_adjust, timeout)
        return PriceDataResult(frame=frame, source="yfinance")
    except Exception as yf_error:
        try:
            frame = fetch_raw_chart(normalized, period, interval, auto_adjust, timeout)
            return PriceDataResult(
                frame=frame,
                source="yahoo_chart_api",
                warning=f"yfinance failed, raw Yahoo chart API used: {yf_error}",
            )
        except Exception as raw_error:
            raise DataProviderError(
                f"Yahoo download failed for {normalized}. yfinance={yf_error}; raw={raw_error}"
            ) from raw_error


def normalize_ticker(ticker: str) -> str:
    return str(ticker or "").strip().upper()


def fetch_yfinance(
    ticker: str,
    period: str,
    interval: str,
    auto_adjust: bool,
    timeout: int,
) -> pd.DataFrame:
    session = make_yahoo_session()
    frame = yf.download(
        ticker,
        period=period,
        interval=interval,
        auto_adjust=auto_adjust,
        progress=False,
        threads=False,
        session=session,
        timeout=timeout,
        multi_level_index=False,
    )
    return normalize_price_frame(frame, ticker)


def fetch_raw_chart(
    ticker: str,
    period: str,
    interval: str,
    auto_adjust: bool,
    timeout: int,
) -> pd.DataFrame:
    session = make_yahoo_session()
    response = session.get(
        YAHOO_CHART_URL.format(ticker=ticker),
        params={
            "range": period,
            "interval": interval,
            "includePrePost": "false",
            "events": "div,splits",
        },
        timeout=timeout,
    )
    if response.status_code >= 400:
        raise DataProviderError(f"Yahoo chart API returned HTTP {response.status_code}.")

    return parse_raw_chart_response(ticker, response.json(), auto_adjust=auto_adjust)


def parse_raw_chart_response(
    ticker: str,
    payload: dict[str, Any],
    auto_adjust: bool = True,
) -> pd.DataFrame:
    chart = payload.get("chart") or {}
    error = chart.get("error")
    if error:
        raise DataProviderError(f"Yahoo chart API error for {ticker}: {error}")

    results = chart.get("result") or []
    if not results:
        raise DataProviderError(f"Yahoo chart API returned no result for {ticker}.")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote_blocks = (result.get("indicators") or {}).get("quote") or []
    if not timestamps or not quote_blocks:
        raise DataProviderError(f"Yahoo chart API returned no OHLCV data for {ticker}.")

    frame = pd.DataFrame(quote_blocks[0])
    frame.index = pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(None)

    adj_blocks = (result.get("indicators") or {}).get("adjclose") or []
    if adj_blocks and "adjclose" in adj_blocks[0]:
        frame["adj_close"] = adj_blocks[0]["adjclose"]

    frame = normalize_price_frame(frame, ticker)

    if auto_adjust and "adj_close" in frame.columns:
        frame = apply_adj_close_ratio(frame)

    return frame


def normalize_price_frame(frame: pd.DataFrame, ticker: str | None = None) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise DataProviderError(f"No price rows returned for {ticker or 'ticker'}.")

    normalized = frame.copy()

    if isinstance(normalized.columns, pd.MultiIndex):
        normalized = flatten_yfinance_columns(normalized, ticker)

    normalized.columns = [normalize_column_name(column) for column in normalized.columns]
    rename_map = {
        "adj close": "adj_close",
        "adjclose": "adj_close",
    }
    normalized = normalized.rename(columns=rename_map)

    missing = [column for column in REQUIRED_COLUMNS if column not in normalized.columns]
    if missing:
        raise DataProviderError(f"Missing required OHLCV columns: {', '.join(missing)}")

    normalized = normalized.loc[:, ~normalized.columns.duplicated()].copy()
    normalized = normalized.sort_index()
    normalized.index = pd.to_datetime(normalized.index)
    if getattr(normalized.index, "tz", None) is not None:
        normalized.index = normalized.index.tz_convert(None)

    numeric_columns = [column for column in normalized.columns if column in set(REQUIRED_COLUMNS) | {"adj_close"}]
    for column in numeric_columns:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    normalized = normalized.dropna(subset=["open", "high", "low", "close"], how="all")
    normalized["volume"] = normalized["volume"].fillna(0)
    if normalized.empty:
        raise DataProviderError(f"Only empty OHLCV rows returned for {ticker or 'ticker'}.")

    return normalized


def flatten_yfinance_columns(frame: pd.DataFrame, ticker: str | None) -> pd.DataFrame:
    columns = frame.columns
    if columns.nlevels != 2:
        flattened = frame.copy()
        flattened.columns = [" ".join(str(part) for part in column if str(part)) for column in columns]
        return flattened

    wanted = normalize_ticker(ticker or "")
    level0 = [normalize_column_name(value) for value in columns.get_level_values(0)]
    level1 = [normalize_column_name(value) for value in columns.get_level_values(1)]
    ohlcv = {"open", "high", "low", "close", "adj close", "adj_close", "volume"}

    field_level = 0 if any(value in ohlcv for value in level0) else 1
    ticker_level = 1 - field_level
    tickers = [str(value).upper() for value in columns.get_level_values(ticker_level)]

    if wanted and wanted in tickers:
        selected = frame.xs(wanted, axis=1, level=ticker_level, drop_level=True)
        return selected.copy()

    selected = frame.copy()
    selected.columns = columns.get_level_values(field_level)
    return selected


def normalize_column_name(column: object) -> str:
    return str(column).strip().replace("_", " ").lower()


def apply_adj_close_ratio(frame: pd.DataFrame) -> pd.DataFrame:
    adjusted = frame.copy()
    close = adjusted["close"].replace(0, pd.NA)
    ratio = adjusted["adj_close"] / close
    ratio = ratio.replace([float("inf"), float("-inf")], pd.NA).fillna(1.0)

    for column in ("open", "high", "low", "close"):
        adjusted[column] = adjusted[column] * ratio

    return adjusted
