"""NSE cash names for the Equity feed.

The worker keeps a cached copy of the public cash list and resolves a posted
name to one ticker. This module does not read another project's database or login.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import threading
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

logger = logging.getLogger("quantivo.feeds")

FYERS_NSE_CM_URL = "https://public.fyers.in/sym_details/NSE_CM.csv"
_CACHE_NAME = "nse_equities.json"
_CACHE_MAX_AGE = timedelta(days=7)
_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_SERIES = frozenset({"EQ", "BE", "BZ", "SM", "ST", "SZ"})
_NAME_SUFFIXES = frozenset(
    {
        "LTD",
        "LIMITED",
        "INC",
        "CORP",
        "CORPORATION",
        "CO",
        "COMPANY",
        "PVT",
        "PRIVATE",
        "THE",
        "AND",
        "OF",
    }
)
_GENERIC_NAME_WORDS = frozenset({"JEWELLER", "JEWELLERS", "JEWELLERY", "JEWELS", "JEWEL", "GEMS"})
_QUERY_TAILS = frozenset({"IND", "INDS", "INDUS", "INDUSTRIES", "ENGG"})
_FUZZY_MIN = 0.90
_FUZZY_GAP = 0.04
_OPTION_TAIL = re.compile(
    r"\s+(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d+(?:\.\d+)?\s+(?:CE|PE)$"
)
_LOCK = threading.Lock()
_LOADED: EquityDirectory | None = None

# Former tickers the channel still writes. Used only when the new symbol is in the cash list.
FORMER_LISTINGS: dict[str, str] = {
    "LTIM": "LTM",
    "ZOMATO": "ETERNAL",
    "TATAMOTORS": "TMPV",
}

# Spellings this Equity channel uses when the ticker is not the same words.
CHANNEL_ALIASES: dict[str, str] = {
    "KROSS": "KROSS",
    "GANDHAR": "GANDHAR",
    "GANDHAR OIL": "GANDHAR",
    "ONWARDTEC": "ONWARDTEC",
    "RENUKA SUGAR": "RENUKA",
    "AEGIES LOGISTICS": "AEGISLOG",
    "AEGIS LOGISTICS": "AEGISLOG",
}


@dataclass(frozen=True)
class EquityRecord:
    symbol: str
    company_name: str
    series: str


@dataclass(frozen=True)
class NameMatch:
    status: str
    symbol: str | None


class EquityDirectory:
    """Exact ticker, then company-name words, then one clear fuzzy company match."""

    def __init__(self, records: list[EquityRecord]) -> None:
        self._by_symbol: dict[str, EquityRecord] = {}
        self._entries: list[tuple[EquityRecord, str, tuple[str, ...]]] = []
        for record in records:
            self._by_symbol.setdefault(record.symbol, record)
            folded = normalize_text(record.symbol).replace(" ", "")
            if folded and folded not in self._by_symbol:
                self._by_symbol[folded] = record
            label = _company_label(record.company_name)
            tokens = tuple(token for token in label.split() if token)
            self._entries.append((record, label, tokens))

    def __len__(self) -> int:
        return len(self._by_symbol)

    def lookup(self, name: str) -> NameMatch:
        raw = _OPTION_TAIL.sub("", name.strip().upper()).strip()
        exact = self._by_symbol.get(raw)
        if exact is not None:
            return NameMatch("matched", exact.symbol)
        key = _prepare_query(name)
        if not key:
            return NameMatch("unmatched", None)
        exact = self._by_symbol.get(key.replace(" ", ""))
        if exact is None and " " not in key:
            exact = self._by_symbol.get(key)
        if exact is not None:
            return NameMatch("matched", exact.symbol)
        renamed = self._by_symbol.get(FORMER_LISTINGS.get(key.replace(" ", ""), ""))
        if renamed is not None:
            return NameMatch("matched", renamed.symbol)

        query_tokens = tuple(token for token in key.split() if token not in _NAME_SUFFIXES)
        if not query_tokens:
            return NameMatch("unmatched", None)
        unique = _unique(
            record
            for record, _label, tokens in self._entries
            if tokens and all(_token_hit(query, tokens) for query in query_tokens)
        )
        if len(unique) == 1:
            return NameMatch("matched", unique[0].symbol)
        if len(unique) > 1:
            return NameMatch("ambiguous", None)
        trimmed = _without_generic_words(query_tokens)
        if trimmed is not None:
            trimmed_hits = _unique(
                record
                for record, _label, tokens in self._entries
                if tokens and all(_token_hit(query, tokens) for query in trimmed)
            )
            if len(trimmed_hits) == 1:
                return NameMatch("matched", trimmed_hits[0].symbol)

        compact = self._compact_hits(key)
        if len(compact) == 1:
            return NameMatch("matched", compact[0].symbol)
        typo = self._symbol_typo(key)
        if typo is not None:
            return typo

        ranked: list[tuple[float, EquityRecord]] = []
        for record, label, _tokens in self._entries:
            if not label:
                continue
            score = SequenceMatcher(None, key, label).ratio()
            if score >= _FUZZY_MIN - _FUZZY_GAP:
                ranked.append((score, record))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked or ranked[0][0] < _FUZZY_MIN:
            shortened = _exact_ticker_without_tail(key, self._by_symbol)
            if shortened is not None:
                return shortened
            return NameMatch("unmatched", None)
        best_score, best = ranked[0]
        close = _unique(record for score, record in ranked if best_score - score < _FUZZY_GAP)
        if len(close) > 1:
            return NameMatch("ambiguous", None)
        if best_score >= _FUZZY_MIN:
            return NameMatch("matched", best.symbol)
        shortened = _exact_ticker_without_tail(key, self._by_symbol)
        if shortened is not None:
            return shortened
        return NameMatch("unmatched", None)

    def _compact_hits(self, key: str) -> list[EquityRecord]:
        query = key.replace(" ", "")
        if len(query) < 8:
            return []
        hits = []
        for record, _label, tokens in self._entries:
            compact = "".join(tokens)
            if len(compact) < 8:
                continue
            fits = compact.startswith(query) and 0 < len(compact) - len(query) <= 6
            if compact == query or fits:
                hits.append(record)
        return _unique(hits)

    def _symbol_typo(self, key: str) -> NameMatch | None:
        if " " in key or len(key) < 8:
            return None
        ranked: list[tuple[int, EquityRecord]] = []
        for symbol, record in self._by_symbol.items():
            if abs(len(symbol) - len(key)) > 2:
                continue
            distance = _levenshtein(key, symbol)
            if distance <= 2:
                ranked.append((distance, record))
        if not ranked:
            return None
        ranked.sort(key=lambda item: item[0])
        best = ranked[0][0]
        winners = _unique(record for distance, record in ranked if distance == best)
        if len(winners) != 1:
            return None
        return NameMatch("matched", winners[0].symbol)


def parse_fyers_nse_cm(text: str) -> list[EquityRecord]:
    records: list[EquityRecord] = []
    for fields in csv.reader(io.StringIO(text)):
        if len(fields) < 10:
            continue
        provider_symbol = fields[9].strip().upper()
        if not provider_symbol.startswith("NSE:"):
            continue
        body = provider_symbol[4:]
        if "-" not in body:
            continue
        symbol, series = body.rsplit("-", 1)
        if not symbol or series not in _SERIES:
            continue
        company = fields[1].strip() if len(fields) > 1 else symbol
        records.append(EquityRecord(symbol=symbol, company_name=company or symbol, series=series))
    return records


def get_equity_directory() -> EquityDirectory | None:
    """Return the cached NSE cash list. Tests set NSE_EQUITY_DIRECTORY=off and skip the download."""

    if os.environ.get("NSE_EQUITY_DIRECTORY") == "off":
        return None
    global _LOADED
    with _LOCK:
        if _LOADED is not None:
            return _LOADED
        cached = _read_cache(allow_stale=False)
        if cached is None:
            cached = _download_cache()
        if cached is None:
            cached = _read_cache(allow_stale=True)
        if not cached:
            return None
        _LOADED = EquityDirectory(cached)
        logger.info("NSE equity directory loaded symbols=%s", len(_LOADED))
        return _LOADED


def reset_equity_directory_cache() -> None:
    global _LOADED
    with _LOCK:
        _LOADED = None


def cached_series() -> dict[str, str]:
    """Series from the local cash-list cache. This does not download."""
    records = _read_cache(allow_stale=True) or []
    index: dict[str, str] = {}
    for record in records:
        current = index.get(record.symbol)
        if current is None or (current != "EQ" and record.series == "EQ"):
            index[record.symbol] = record.series
    return index


def normalize_text(value: str) -> str:
    normalized = value.upper().replace("&", " AND ")
    normalized = re.sub(r"[^A-Z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def alias_symbol(name: str) -> str | None:
    return CHANNEL_ALIASES.get(normalize_text(name))


def _cache_path() -> Path:
    return _BACKEND_ROOT / "data" / _CACHE_NAME


def _read_cache(*, allow_stale: bool) -> list[EquityRecord] | None:
    path = _cache_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched = datetime.fromisoformat(payload["fetched_at"])
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    if not allow_stale and datetime.now(UTC) - fetched > _CACHE_MAX_AGE:
        return None
    return [
        EquityRecord(
            symbol=item["symbol"],
            company_name=item["company_name"],
            series=item.get("series") or "EQ",
        )
        for item in payload.get("rows") or []
        if item.get("symbol")
    ]


def _download_cache() -> list[EquityRecord] | None:
    request = urllib.request.Request(FYERS_NSE_CM_URL, headers={"User-Agent": "Quantivo/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8", errors="replace")
    except OSError:
        logger.exception("NSE equity directory download failed")
        return None
    records = parse_fyers_nse_cm(text)
    if not records:
        return None
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "source": "fyers_nse_cm",
        "rows": [
            {"symbol": record.symbol, "company_name": record.company_name, "series": record.series}
            for record in records
        ],
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(body), encoding="utf-8")
    temporary.replace(path)
    return records


def _company_label(company_name: str) -> str:
    tokens = [
        token for token in normalize_text(company_name).split() if token not in _NAME_SUFFIXES
    ]
    return " ".join(tokens)


def _without_generic_words(query_tokens: tuple[str, ...]) -> tuple[str, ...] | None:
    trimmed = tuple(token for token in query_tokens if token not in _GENERIC_NAME_WORDS)
    if len(trimmed) < 2 or len(trimmed) == len(query_tokens):
        return None
    return trimmed


def _prepare_query(name: str) -> str:
    return _OPTION_TAIL.sub("", normalize_text(name)).strip()


def _exact_ticker_without_tail(key: str, by_symbol: dict[str, EquityRecord]) -> NameMatch | None:
    tokens = key.split()
    if len(tokens) < 2 or tokens[-1] not in _QUERY_TAILS:
        return None
    short = " ".join(tokens[:-1])
    if " " in short:
        return None
    record = by_symbol.get(short)
    if record is None:
        return None
    return NameMatch("matched", record.symbol)


def _token_hit(query: str, company_tokens: tuple[str, ...]) -> bool:
    for token in company_tokens:
        if token == query:
            return True
        if len(query) >= 4 and token.startswith(query) and len(token) - len(query) <= 3:
            return True
    if 2 <= len(query) <= 4 and query.isalpha():
        for start in range(len(company_tokens)):
            joined = ""
            for token in company_tokens[start:]:
                if len(token) != 1:
                    break
                joined += token
                if joined == query:
                    return True
    return False


def _levenshtein(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for index, left_char in enumerate(left, start=1):
        current = [index]
        for column, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            current.append(min(current[-1] + 1, previous[column] + 1, previous[column - 1] + cost))
        previous = current
    return previous[-1]


def _unique(records) -> list[EquityRecord]:
    seen: set[str] = set()
    unique: list[EquityRecord] = []
    for record in records:
        if record.symbol in seen:
            continue
        seen.add(record.symbol)
        unique.append(record)
    return unique
