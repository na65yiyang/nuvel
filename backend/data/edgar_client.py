import time
import logging
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Nuvel Research contact@nuvel.co"}
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}"


def _get(url: str, *, stream: bool = False, max_retries: int = 3) -> requests.Response:
    """GET with exponential backoff on transient HTTP errors."""
    delay = 1.0
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=_HEADERS, stream=stream, timeout=30)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (429, 500, 502, 503, 504):
                logger.warning(
                    "EDGAR %s → %s, retry %d/%d in %.1fs",
                    url, resp.status_code, attempt + 1, max_retries, delay,
                )
                time.sleep(delay)
                delay *= 2
                continue
            resp.raise_for_status()
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning(
                "Request error %s (attempt %d/%d): %s",
                url, attempt + 1, max_retries, exc,
            )
            time.sleep(delay)
            delay *= 2

    raise RuntimeError(
        f"Failed to GET {url} after {max_retries} retries"
    ) from last_exc


def _resolve_cik(ticker: str) -> str:
    """Return zero-padded 10-digit CIK for a ticker symbol."""
    data = _get(_TICKERS_URL).json()
    ticker_upper = ticker.upper()
    for entry in data.values():
        if entry["ticker"].upper() == ticker_upper:
            return str(entry["cik_str"]).zfill(10)
    raise ValueError(f"Ticker '{ticker}' not found in SEC company_tickers.json")


def get_latest_filing_url(ticker: str, form_type: str) -> str:
    """
    Return the URL of the primary document in the most recent SEC filing
    of form_type (e.g. '10-K', '10-Q') for the given ticker.

    Uses the submissions API primaryDocument field — no extra index fetch needed.
    """
    cik = _resolve_cik(ticker)
    submissions = _get(_SUBMISSIONS_URL.format(cik=cik)).json()

    recent = submissions["filings"]["recent"]
    forms = recent["form"]
    accessions = recent["accessionNumber"]
    primary_docs = recent["primaryDocument"]
    dates = recent["filingDate"]

    # EDGAR returns filings newest-first; take the first match
    for form, accession, doc, date in zip(forms, accessions, primary_docs, dates):
        if form == form_type:
            accession_clean = accession.replace("-", "")
            cik_int = int(cik)
            url = _ARCHIVES_BASE.format(
                cik=cik_int,
                accession=accession_clean,
                doc=doc,
            )
            logger.info("Resolved %s %s (filed %s) → %s", ticker, form_type, date, url)
            return url

    raise ValueError(
        f"No {form_type} filing found for '{ticker}' in EDGAR submissions"
    )


def download_filing_pdf(filing_url: str, ticker: str, year: str) -> str:
    """
    Download the filing document to /tmp/{ticker}_{year}.pdf and return
    the local path. EDGAR primary documents are usually inline HTML (iXBRL);
    the .pdf extension is kept to match the project spec.
    """
    dest = Path(f"/tmp/{ticker.upper()}_{year}.pdf")
    resp = _get(filing_url, stream=True)

    with dest.open("wb") as fh:
        for chunk in resp.iter_content(chunk_size=65536):
            fh.write(chunk)

    size_kb = dest.stat().st_size // 1024
    logger.info("Saved %s (%d KB) → %s", filing_url, size_kb, dest)
    return str(dest)
