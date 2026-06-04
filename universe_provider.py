from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from html import unescape
from io import StringIO
from pathlib import Path
from typing import Iterable

import pandas as pd
from curl_cffi import requests


UNIVERSE_CUSTOM = "Custom Watchlist"
UNIVERSE_NASDAQ100 = "NASDAQ100"
UNIVERSE_KOSPI200 = "KOSPI200"
UNIVERSE_KOSDAQ150 = "KOSDAQ150"
UNIVERSE_OPTIONS = [UNIVERSE_CUSTOM, UNIVERSE_NASDAQ100, UNIVERSE_KOSPI200, UNIVERSE_KOSDAQ150]

UNIVERSE_COLUMNS = ["universe", "symbol", "name", "market", "source", "as_of"]
DATA_DIR = Path(__file__).resolve().parent / "data" / "universes"

NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
NAVER_ENTRY_URL = "https://finance.naver.com/sise/entryJongmok.naver?code={code}&page={page}"
INVESTING_KOSDAQ150_URL = "https://ca.investing.com/indices/kosdaq-150-components"


class UniverseProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class UniverseRefreshResult:
    frame: pd.DataFrame
    source: str
    warning: str | None = None


def load_builtin_universe(universe: str) -> pd.DataFrame:
    if universe == UNIVERSE_CUSTOM:
        return pd.DataFrame(columns=UNIVERSE_COLUMNS)

    path = DATA_DIR / f"{universe.lower()}.csv"
    if not path.exists():
        raise UniverseProviderError(f"내장 유니버스 CSV가 없습니다: {path}")
    frame = pd.read_csv(path, dtype=str).fillna("")
    return normalize_universe_frame(frame, universe=universe)


def refresh_universe(universe: str) -> UniverseRefreshResult:
    if universe == UNIVERSE_NASDAQ100:
        html = request_text(NASDAQ100_URL)
        frame = parse_nasdaq100_html(html, as_of=today_text())
        return UniverseRefreshResult(frame=frame, source=NASDAQ100_URL)

    if universe == UNIVERSE_KOSPI200:
        frame = refresh_naver_components(
            universe=UNIVERSE_KOSPI200,
            code="KPI200",
            suffix=".KS",
            market="KOSPI",
            source="Naver Finance KPI200",
        )
        return UniverseRefreshResult(frame=frame, source="Naver Finance KPI200")

    if universe == UNIVERSE_KOSDAQ150:
        warning: str | None = None
        try:
            frame = refresh_naver_components(
                universe=UNIVERSE_KOSDAQ150,
                code="KQ150",
                suffix=".KQ",
                market="KOSDAQ",
                source="Naver Finance KQ150",
            )
            if len(frame) >= 100 and not looks_like_kospi200_misroute(frame):
                return UniverseRefreshResult(frame=frame, source="Naver Finance KQ150")
            warning = f"Naver KQ150 결과가 유효하지 않아 Investing.com fallback을 사용했습니다. rows={len(frame)}"
        except Exception as exc:
            warning = f"Naver KQ150 갱신 실패 후 Investing.com fallback 사용: {exc}"

        html = request_text(INVESTING_KOSDAQ150_URL)
        frame = parse_investing_components_html(
            html,
            universe=UNIVERSE_KOSDAQ150,
            suffix=".KQ",
            market="KOSDAQ",
            source="Investing.com KOSDAQ150",
            as_of=today_text(),
        )
        return UniverseRefreshResult(frame=frame, source="Investing.com KOSDAQ150", warning=warning)

    raise UniverseProviderError(f"지원하지 않는 유니버스입니다: {universe}")


def refresh_naver_components(
    *,
    universe: str,
    code: str,
    suffix: str,
    market: str,
    source: str,
    max_pages: int = 40,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        html = request_text(NAVER_ENTRY_URL.format(code=code, page=page), encoding="euc-kr")
        parsed = parse_naver_components_html(
            html,
            universe=universe,
            suffix=suffix,
            market=market,
            source=source,
            as_of=today_text(),
        )
        symbols = [symbol for symbol in parsed["symbol"].tolist() if symbol not in seen]
        if not symbols:
            if page > 1:
                break
            continue
        frames.append(parsed.loc[parsed["symbol"].isin(symbols)])
        seen.update(symbols)

    if not frames:
        raise UniverseProviderError(f"{source}에서 구성 종목을 찾지 못했습니다.")
    return normalize_universe_frame(pd.concat(frames, ignore_index=True), universe=universe)


def parse_nasdaq100_html(html: str, as_of: str | None = None) -> pd.DataFrame:
    tables = pd.read_html(StringIO(html))
    for table in tables:
        columns = [str(column) for column in table.columns]
        ticker_col = next((column for column in table.columns if "Ticker" in str(column)), None)
        company_col = next((column for column in table.columns if "Company" in str(column)), None)
        if ticker_col is None or company_col is None:
            continue

        rows = []
        for _, row in table.iterrows():
            raw_symbol = clean_text(row.get(ticker_col, ""))
            name = clean_text(row.get(company_col, ""))
            if not raw_symbol or raw_symbol.lower() == "nan":
                continue
            symbol = raw_symbol.replace(".", "-").upper()
            rows.append(
                {
                    "universe": UNIVERSE_NASDAQ100,
                    "symbol": symbol,
                    "name": name,
                    "market": "NASDAQ",
                    "source": NASDAQ100_URL,
                    "as_of": as_of or today_text(),
                }
            )
        if rows:
            return normalize_universe_frame(pd.DataFrame(rows), universe=UNIVERSE_NASDAQ100)

    raise UniverseProviderError("Wikipedia Nasdaq-100 테이블에서 Ticker/Company 컬럼을 찾지 못했습니다.")


def parse_naver_components_html(
    html: str,
    *,
    universe: str,
    suffix: str,
    market: str,
    source: str,
    as_of: str | None = None,
) -> pd.DataFrame:
    rows = []
    pattern = re.compile(r"item/main\.naver\?code=(\d{6})[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
    for code, raw_name in pattern.findall(html):
        name = clean_text(re.sub(r"<[^>]+>", " ", raw_name))
        rows.append(
            {
                "universe": universe,
                "symbol": f"{code}{suffix}",
                "name": name,
                "market": market,
                "source": source,
                "as_of": as_of or today_text(),
            }
        )
    return normalize_universe_frame(pd.DataFrame(rows), universe=universe)


def parse_investing_components_html(
    html: str,
    *,
    universe: str,
    suffix: str,
    market: str,
    source: str,
    as_of: str | None = None,
) -> pd.DataFrame:
    collections = extract_investing_asset_collections(html)
    best: list[dict[str, object]] = []
    for collection in collections:
        rows = []
        for item in collection:
            raw_symbol = str(item.get("symbol", "")).strip()
            if not re.fullmatch(r"\d{6}", raw_symbol):
                continue
            name = clean_text(item.get("name") or item.get("title") or "")
            if not name:
                continue
            rows.append(
                {
                    "universe": universe,
                    "symbol": f"{raw_symbol}{suffix}",
                    "name": name,
                    "market": market,
                    "source": source,
                    "as_of": as_of or today_text(),
                }
            )
        if len(rows) > len(best):
            best = rows

    if not best:
        raise UniverseProviderError(f"{source} assetsCollection에서 6자리 한국 종목 코드를 찾지 못했습니다.")
    return normalize_universe_frame(pd.DataFrame(best), universe=universe)


def extract_investing_asset_collections(html: str) -> list[list[dict[str, object]]]:
    collections: list[list[dict[str, object]]] = []
    marker = '"assetsCollection":{"_collection":['
    start = 0
    while True:
        marker_at = html.find(marker, start)
        if marker_at == -1:
            break
        array_start = html.find("[", marker_at)
        if array_start == -1:
            break
        array_end = find_balanced_array_end(html, array_start)
        if array_end is None:
            start = marker_at + len(marker)
            continue
        try:
            parsed = json.loads(html[array_start : array_end + 1])
        except json.JSONDecodeError:
            start = array_end + 1
            continue
        if isinstance(parsed, list):
            collections.append(parsed)
        start = array_end + 1
    return collections


def find_balanced_array_end(text: str, start: int) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index
    return None


def normalize_universe_frame(frame: pd.DataFrame, *, universe: str | None = None) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=UNIVERSE_COLUMNS)

    normalized = frame.copy()
    for column in UNIVERSE_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = ""
    if universe is not None:
        normalized["universe"] = universe

    normalized = normalized[UNIVERSE_COLUMNS].fillna("")
    for column in UNIVERSE_COLUMNS:
        normalized[column] = normalized[column].map(clean_text)
    normalized["symbol"] = normalized["symbol"].str.upper()
    normalized = normalized.loc[normalized["symbol"].ne("")]
    normalized = normalized.drop_duplicates("symbol", keep="first").reset_index(drop=True)
    return normalized


def looks_like_kospi200_misroute(frame: pd.DataFrame) -> bool:
    if frame.empty or "symbol" not in frame.columns:
        return False
    first_symbols = set(frame["symbol"].head(30).astype(str))
    kospi_large_caps_as_kq = {"005930.KQ", "000660.KQ", "005380.KQ", "373220.KQ"}
    return len(first_symbols & kospi_large_caps_as_kq) >= 2


def custom_watchlist_frame(symbols: Iterable[str]) -> pd.DataFrame:
    rows = []
    for symbol in symbols:
        clean_symbol = clean_text(symbol).upper()
        if not clean_symbol:
            continue
        rows.append(
            {
                "universe": UNIVERSE_CUSTOM,
                "symbol": clean_symbol,
                "name": clean_symbol,
                "market": "CUSTOM",
                "source": "User watchlist",
                "as_of": today_text(),
            }
        )
    return normalize_universe_frame(pd.DataFrame(rows), universe=UNIVERSE_CUSTOM)


def preview_symbols(frame: pd.DataFrame, limit: int = 80) -> str:
    if frame.empty:
        return ""
    labels = [
        f"{row.symbol}  {row.name}".strip()
        for row in frame[["symbol", "name"]].head(limit).itertuples(index=False)
    ]
    suffix = "" if len(frame) <= limit else f"\n... +{len(frame) - limit} more"
    return "\n".join(labels) + suffix


def split_screening_results(results: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if results.empty:
        empty = pd.DataFrame()
        return empty, empty, empty

    frame = results.copy()
    for column in ["top_score", "bottom_score"]:
        frame[column] = pd.to_numeric(frame.get(column, 0), errors="coerce").fillna(0)
    if "quality" not in frame.columns:
        frame["quality"] = ""
    if "days_since_signal" not in frame.columns:
        frame["days_since_signal"] = 9999
    if "status" not in frame.columns:
        frame["status"] = "ok"
    if "zone" not in frame.columns:
        frame["zone"] = ""

    frame["_quality_rank"] = frame["quality"].map(quality_rank).fillna(0)
    frame["_days_rank"] = pd.to_numeric(frame["days_since_signal"], errors="coerce").fillna(9999)

    ok_status = frame["status"].isin(["ok", "fallback"])
    failures = frame.loc[~ok_status].copy()
    ok = frame.loc[ok_status].copy()
    top = ok.loc[(ok["zone"] == "고점 후보") | (ok["top_score"] > ok["bottom_score"])].copy()
    bottom = ok.loc[(ok["zone"] == "저점 후보") | (ok["bottom_score"] > ok["top_score"])].copy()

    top = top.sort_values(["_quality_rank", "top_score", "_days_rank"], ascending=[False, False, True])
    bottom = bottom.sort_values(["_quality_rank", "bottom_score", "_days_rank"], ascending=[False, False, True])
    all_rows = frame.sort_values(["_quality_rank", "top_score", "bottom_score", "_days_rank"], ascending=[False, False, False, True])
    return drop_internal_columns(top), drop_internal_columns(bottom), drop_internal_columns(pd.concat([all_rows, failures], ignore_index=True).drop_duplicates("symbol", keep="first"))


def quality_rank(value: object) -> int:
    text = str(value or "")
    if text == "강함":
        return 3
    if text == "주의":
        return 2
    if text == "관찰":
        return 1
    return 0


def drop_internal_columns(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.drop(columns=[column for column in frame.columns if column.startswith("_")], errors="ignore").reset_index(drop=True)


def request_text(url: str, encoding: str | None = None) -> str:
    response = requests.get(url, impersonate="chrome", verify=False, timeout=25)
    response.raise_for_status()
    if encoding:
        response.encoding = encoding
    return response.text


def clean_text(value: object) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"\[[^\]]+\]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def today_text() -> str:
    return date.today().isoformat()
