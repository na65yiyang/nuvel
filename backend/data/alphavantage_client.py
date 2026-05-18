import json
import os
import time
import logging
import threading
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.alphavantage.co/query"

# Free tier: 5 requests / minute per API key.
# With Celery prefork each *process* owns its own limiter, so set the interval
# conservatively enough that two concurrent workers stay within the cap.
# Formula: 60 s / 5 req = 12 s minimum; 15 s gives headroom for 2 workers
# (2 workers × 4 req/min each = 8 req/min < 10, safely under the 5-req/min
#  per-key limit when each worker self-throttles to one call every 15 s).
#
# NOTE: this limiter coordinates threads within a single process.  If you run
# more than one Celery worker process with the same API key, reduce concurrency
# to 1 (`--concurrency=1`) or switch to a Redis-backed rate limiter.
_MIN_INTERVAL = 15.0  # seconds between consecutive requests (per process)

# HTTP status codes that are permanent failures — never retry these.
_NON_RETRIABLE = frozenset({400, 401, 403, 404, 405, 422})

# How long to wait after AlphaVantage returns a per-minute "Note" response.
# The free tier resets every 60 s; sleep 65 s to be safe.
_NOTE_SLEEP = 65.0

_INCOME_COLS = [
    "fiscalDateEnding",
    "totalRevenue",
    "grossProfit",
    "operatingIncome",
    "netIncome",
    "ebitda",
    "eps",
    "researchAndDevelopment",
    "sellingGeneralAndAdministrative",
]
_BALANCE_COLS = [
    "fiscalDateEnding",
    "cashAndCashEquivalentsAtCarryingValue",
    "currentNetReceivables",
    "inventory",
    "totalCurrentAssets",
    "totalAssets",
    "totalCurrentLiabilities",
    "longTermDebt",
    "totalShareholderEquity",
    "goodwill",
]
_CASHFLOW_COLS = [
    "fiscalDateEnding",
    "operatingCashflow",
    "capitalExpenditures",
    "freeCashFlow",
]


# ---------------------------------------------------------------------------
# Thread-safe rate limiter
# ---------------------------------------------------------------------------

class _RateLimiter:
    """
    Ensures at least _MIN_INTERVAL seconds between consecutive API calls.

    Thread-safety: the slot reservation happens under a lock, but the actual
    sleep happens *outside* the lock so that other threads can reserve their
    own future slots concurrently instead of queuing behind the sleeping thread.
    """

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._next_allowed: float = 0.0   # monotonic time of next allowed call
        self._lock = threading.Lock()

    def wait(self) -> None:
        # Bug fix: reserve the slot under the lock, then sleep outside it.
        # Previously `time.sleep()` ran inside the lock, blocking every other
        # thread for the full interval even though they only need a moment to
        # reserve their own future slot.
        with self._lock:
            now = time.monotonic()
            sleep_for = max(0.0, self._next_allowed - now)
            # Reserve the next slot (this thread claims [next_allowed, next_allowed+ε])
            self._next_allowed = max(now, self._next_allowed) + self._min_interval

        if sleep_for > 0:
            logger.debug("Rate limit: sleeping %.2fs before next API call", sleep_for)
            time.sleep(sleep_for)


_rate_limiter = _RateLimiter(_MIN_INTERVAL)


# ---------------------------------------------------------------------------
# Disk cache — avoids burning free-tier quota on repeated runs
# ---------------------------------------------------------------------------

_CACHE_DIR = "/tmp/av_cache"
_CACHE_TTL = 86400  # 24 hours — AlphaVantage annual data doesn't change intraday


def _cache_path(function: str, ticker: str) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f"{ticker.upper()}_{function}.json")


def _load_cache(function: str, ticker: str) -> dict[str, Any] | None:
    path = _cache_path(function, ticker)
    try:
        if time.time() - os.path.getmtime(path) < _CACHE_TTL:
            with open(path) as fh:
                data = json.load(fh)
            logger.info("Cache hit for %s/%s", function, ticker)
            return data
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        pass
    return None


def _save_cache(function: str, ticker: str, data: dict[str, Any]) -> None:
    try:
        with open(_cache_path(function, ticker), "w") as fh:
            json.dump(data, fh)
    except OSError as exc:
        logger.warning("Could not write cache for %s/%s: %s", function, ticker, exc)


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

def _fetch(function: str, ticker: str, max_retries: int = 3) -> dict[str, Any]:
    """
    Call one AlphaVantage endpoint with rate limiting and exponential backoff.

    Retry behaviour:
    - Permanent 4xx errors (400/401/403/404/422): raised immediately, no retry.
    - Transient errors (429, 5xx, network): retried up to max_retries times
      with exponential backoff starting at 2 s.
    - "Note" responses (per-minute rate limit hit): sleeps _NOTE_SLEEP seconds
      and retries; each "Note" response consumes one retry slot.
    - "Error Message" in payload (bad symbol / function): raised immediately.
    - "Information" in payload (API key issue): raised immediately.
    """
    cached = _load_cache(function, ticker)
    if cached is not None:
        return cached

    api_key = os.environ.get("ALPHAVANTAGE_API_KEY", "")
    if not api_key:
        raise EnvironmentError("ALPHAVANTAGE_API_KEY environment variable not set")

    params = {"function": function, "symbol": ticker, "apikey": api_key}
    delay = 2.0
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        _rate_limiter.wait()
        try:
            resp = requests.get(_BASE_URL, params=params, timeout=30)

            # Bug fix: don't retry permanent client errors — they will never
            # succeed and each retry burns a precious API request.
            if resp.status_code in _NON_RETRIABLE:
                raise RuntimeError(
                    f"AlphaVantage returned HTTP {resp.status_code} for "
                    f"{function}/{ticker} — not retrying"
                )

            if resp.status_code != 200:
                # Retriable: 429 Too Many Requests, 5xx server errors
                exc = requests.HTTPError(
                    f"HTTP {resp.status_code}", response=resp
                )
                logger.warning(
                    "AlphaVantage HTTP %d for %s/%s (attempt %d/%d)",
                    resp.status_code, function, ticker, attempt, max_retries,
                )
                last_exc = exc
                time.sleep(delay)
                delay *= 2
                continue

            data = resp.json()

            # AlphaVantage embeds errors inside 200 responses.

            if "Error Message" in data:
                # Permanent: bad ticker, unknown function, etc. — no retry.
                raise ValueError(
                    f"AlphaVantage rejected {function}/{ticker}: "
                    f"{data['Error Message']}"
                )

            if "Information" in data:
                # Permanent: invalid or exhausted API key.
                raise ValueError(
                    f"AlphaVantage API key issue: {data['Information']}"
                )

            if "Note" in data:
                # Bug fix: per-minute rate limit hit. The backoff must cover
                # the full 60-second window; 2 s was far too short and just
                # triggered another "Note" on the very next call.
                logger.warning(
                    "AlphaVantage rate-limit 'Note' (attempt %d/%d): "
                    "sleeping %.0f s for per-minute window to reset",
                    attempt, max_retries, _NOTE_SLEEP,
                )
                last_exc = RuntimeError(f"AlphaVantage rate-limit Note: {data['Note']}")
                time.sleep(_NOTE_SLEEP)
                # Reset backoff — after the window resets, the next call
                # should succeed without additional delay.
                delay = 2.0
                continue

            _save_cache(function, ticker, data)
            return data

        except (requests.RequestException,) as exc:
            last_exc = exc
            logger.warning(
                "AlphaVantage %s/%s network error (attempt %d/%d): %s",
                function, ticker, attempt, max_retries, exc,
            )
            if attempt < max_retries:
                time.sleep(delay)
                delay *= 2

    raise RuntimeError(
        f"AlphaVantage {function} for {ticker} failed after {max_retries} retries"
    ) from last_exc


# ---------------------------------------------------------------------------
# DataFrame helpers
# ---------------------------------------------------------------------------

def _to_dataframe(
    reports: list[dict],
    required_cols: list[str],
    n_years: int = 5,
) -> pd.DataFrame:
    """
    Convert a list of annual-report dicts to a tidy DataFrame.

    - Keeps only the `n_years` most-recent rows (AlphaVantage returns newest first).
    - Ensures every column in `required_cols` is present (fills missing with NaN).
    - Coerces all numeric columns from string to float64 (AlphaVantage returns
      strings; missing values are represented as "None", "", or similar).
    - Bug fix: uses `errors="coerce"` for `pd.to_datetime` so that a stray
      "None" or malformed date string becomes NaT and is dropped rather than
      crashing the entire fetch.
    """
    df = pd.DataFrame(reports[:n_years])

    # Guarantee all required columns exist before any type coercion
    for col in required_cols:
        if col not in df.columns:
            df[col] = pd.NA

    # Coerce numeric columns — `errors="coerce"` turns any non-numeric string
    # (including AlphaVantage's "None" sentinel) into NaN without an exception.
    numeric_cols = [c for c in required_cols if c != "fiscalDateEnding"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Bug fix: add errors="coerce" so malformed/missing dates become NaT
    # instead of raising ValueError.  Drop those rows to keep the DataFrame
    # consistent (a row with NaT fiscal date is unusable downstream).
    df["fiscalDateEnding"] = pd.to_datetime(
        df["fiscalDateEnding"], errors="coerce"
    )
    df = df.dropna(subset=["fiscalDateEnding"])

    return df[required_cols].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_income_statement(ticker: str) -> pd.DataFrame:
    """Annual income statement for the last 5 fiscal years."""
    data = _fetch("INCOME_STATEMENT", ticker)
    reports = data.get("annualReports", [])
    if not reports:
        raise ValueError(f"No annual income statement data returned for {ticker}")
    return _to_dataframe(reports, _INCOME_COLS)


def get_balance_sheet(ticker: str) -> pd.DataFrame:
    """Annual balance sheet for the last 5 fiscal years."""
    data = _fetch("BALANCE_SHEET", ticker)
    reports = data.get("annualReports", [])
    if not reports:
        raise ValueError(f"No annual balance sheet data returned for {ticker}")
    return _to_dataframe(reports, _BALANCE_COLS)


def get_cash_flow(ticker: str) -> pd.DataFrame:
    """Annual cash flow statement for the last 5 fiscal years."""
    data = _fetch("CASH_FLOW", ticker)
    reports = data.get("annualReports", [])
    if not reports:
        raise ValueError(f"No annual cash flow data returned for {ticker}")
    return _to_dataframe(reports, _CASHFLOW_COLS)


def get_all_statements(ticker: str) -> dict[str, pd.DataFrame]:
    """
    Fetch all three financial statements for ticker.
    Returns {"income": df, "balance": df, "cashflow": df}.

    The rate limiter ensures the three sequential requests stay within the
    AlphaVantage free-tier cap (5 req/min per key).  Run the Celery worker
    with --concurrency=1 when using a free-tier key to avoid two workers
    doubling the request rate and hitting the cap.
    """
    logger.info("Fetching all financial statements for %s", ticker)
    return {
        "income":   get_income_statement(ticker),
        "balance":  get_balance_sheet(ticker),
        "cashflow": get_cash_flow(ticker),
    }
