"""
Unit tests for data/edgar_client.py.
All HTTP calls are mocked — no real SEC EDGAR requests are made.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

# Minimal company_tickers.json payload (same shape as the real endpoint)
_TICKERS_PAYLOAD = {
    "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA Corp"},
    "1": {"cik_str": 320193,  "ticker": "AAPL", "title": "Apple Inc"},
}

# Minimal submissions payload for NVDA
_SUBMISSIONS_PAYLOAD = {
    "filings": {
        "recent": {
            "form":             ["10-K", "10-Q", "8-K"],
            "accessionNumber":  ["0001045810-25-000024", "0001045810-24-000078", "0001045810-24-000050"],
            "primaryDocument":  ["nvda-20250126.htm", "nvda-20241027.htm", "nvda-form8k.htm"],
            "filingDate":       ["2025-02-26", "2024-11-21", "2024-10-01"],
        }
    }
}


def _mock_response(payload: dict | bytes, status: int = 200) -> MagicMock:
    """Return a requests.Response-like mock for the given payload."""
    resp = MagicMock()
    resp.status_code = status
    if isinstance(payload, dict):
        resp.json.return_value = payload
        resp.iter_content.return_value = [json.dumps(payload).encode()]
    else:
        resp.json.side_effect = ValueError("not JSON")
        resp.iter_content.return_value = [payload]
    return resp


# ── _resolve_cik ──────────────────────────────────────────────────────────────

class TestResolveCik:
    def test_known_ticker_returns_zero_padded_cik(self):
        from data.edgar_client import _resolve_cik

        with patch("data.edgar_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(_TICKERS_PAYLOAD)
            cik = _resolve_cik("NVDA")

        assert cik == "0001045810"
        assert len(cik) == 10

    def test_case_insensitive(self):
        from data.edgar_client import _resolve_cik

        with patch("data.edgar_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(_TICKERS_PAYLOAD)
            cik = _resolve_cik("nvda")

        assert cik == "0001045810"

    def test_unknown_ticker_raises(self):
        from data.edgar_client import _resolve_cik

        with patch("data.edgar_client.requests.get") as mock_get:
            mock_get.return_value = _mock_response(_TICKERS_PAYLOAD)
            with pytest.raises(ValueError, match="not found"):
                _resolve_cik("ZZZZ")


# ── get_latest_filing_url ─────────────────────────────────────────────────────

class TestGetLatestFilingUrl:
    def _setup_mocks(self, mock_get):
        """Two sequential GET calls: tickers → submissions."""
        mock_get.side_effect = [
            _mock_response(_TICKERS_PAYLOAD),
            _mock_response(_SUBMISSIONS_PAYLOAD),
        ]

    def test_returns_correct_10k_url(self):
        from data.edgar_client import get_latest_filing_url

        with patch("data.edgar_client.requests.get") as mock_get:
            self._setup_mocks(mock_get)
            url = get_latest_filing_url("NVDA", "10-K")

        # accession 0001045810-25-000024 → clean → 0001045810250000 24
        assert "nvda-20250126.htm" in url
        assert "1045810" in url  # CIK without leading zeros in path

    def test_10q_url_is_found(self):
        """The mock submissions payload includes a 10-Q — verify it resolves."""
        from data.edgar_client import get_latest_filing_url

        with patch("data.edgar_client.requests.get") as mock_get:
            self._setup_mocks(mock_get)
            url = get_latest_filing_url("NVDA", "10-Q")

        assert "nvda-20241027.htm" in url

    def test_rare_form_type_raises(self):
        from data.edgar_client import get_latest_filing_url

        payload = {
            "filings": {"recent": {
                "form": ["10-K"],
                "accessionNumber": ["0001045810-25-000024"],
                "primaryDocument": ["nvda-20250126.htm"],
                "filingDate": ["2025-02-26"],
            }}
        }
        with patch("data.edgar_client.requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_response(_TICKERS_PAYLOAD),
                _mock_response(payload),
            ]
            with pytest.raises(ValueError, match="No 20-F"):
                get_latest_filing_url("NVDA", "20-F")


# ── download_filing_pdf ───────────────────────────────────────────────────────

class TestDownloadFilingPdf:
    def test_saves_file_and_returns_path(self, tmp_path, monkeypatch):
        from data.edgar_client import download_filing_pdf

        content = b"<html>fake 10-K filing</html>"
        resp = MagicMock()
        resp.status_code = 200
        resp.iter_content.return_value = [content]

        # Redirect Path("/tmp/NVDA_2024.pdf") to tmp_path/NVDA_2024.pdf
        import data.edgar_client as mod

        class _TmpPath:
            def __init__(self, p):
                self._p = tmp_path / str(p).split("/")[-1]  # just the filename
            def open(self, mode): return self._p.open(mode)
            def stat(self): return self._p.stat()
            def __str__(self): return str(self._p)

        monkeypatch.setattr(mod, "Path", _TmpPath)

        with patch("data.edgar_client.requests.get", return_value=resp):
            path = download_filing_pdf(
                "https://www.sec.gov/fake/nvda.htm", "NVDA", "2024"
            )

        assert path.endswith("NVDA_2024.pdf")
        assert (tmp_path / "NVDA_2024.pdf").read_bytes() == content

    def test_retries_on_transient_error(self):
        from data.edgar_client import _get

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {}

        fail_resp = MagicMock()
        fail_resp.status_code = 503

        with patch("data.edgar_client.requests.get") as mock_get, \
             patch("data.edgar_client.time.sleep"):            # don't actually sleep
            mock_get.side_effect = [fail_resp, ok_resp]
            result = _get("https://example.com/test")

        assert result.status_code == 200
        assert mock_get.call_count == 2
