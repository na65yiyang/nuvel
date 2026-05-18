"""
Unit tests for data/alphavantage_client.py.
All HTTP calls are mocked — no real AlphaVantage requests are made.
"""
import os
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _av_response(annual_reports: list[dict], key: str = "annualReports") -> dict:
    """Wrap report rows in the AlphaVantage envelope."""
    return {key: annual_reports}


def _income_row(year: str = "2024-01-28") -> dict:
    return {
        "fiscalDateEnding":                   year,
        "totalRevenue":                       "130497000000",
        "grossProfit":                        "97796000000",
        "operatingIncome":                    "81614000000",
        "netIncome":                          "72880000000",
        "ebitda":                             "85000000000",
        "eps":                                "2.99",
        "researchAndDevelopment":             "12908000000",
        "sellingGeneralAndAdministrative":    "3332000000",
    }


def _mock_get(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


# ── _fetch ────────────────────────────────────────────────────────────────────

_no_cache = patch("data.alphavantage_client._load_cache", return_value=None)
_no_save  = patch("data.alphavantage_client._save_cache")


class TestFetch:
    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
        from data.alphavantage_client import _fetch
        with _no_cache, _no_save, pytest.raises(EnvironmentError, match="ALPHAVANTAGE_API_KEY"):
            _fetch("INCOME_STATEMENT", "NVDA")

    def test_raises_on_error_message_in_payload(self, monkeypatch):
        monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "test-key")
        payload = {"Error Message": "Invalid API call."}
        with patch("data.alphavantage_client.requests.get", return_value=_mock_get(payload)), \
             patch("data.alphavantage_client._rate_limiter.wait"), \
             _no_cache, _no_save:
            from data.alphavantage_client import _fetch
            with pytest.raises((ValueError, RuntimeError)):
                _fetch("INCOME_STATEMENT", "NVDA")

    def test_raises_on_information_key(self, monkeypatch):
        monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "test-key")
        payload = {"Information": "Please consider subscribing to a premium plan."}
        with patch("data.alphavantage_client.requests.get", return_value=_mock_get(payload)), \
             patch("data.alphavantage_client._rate_limiter.wait"), \
             _no_cache, _no_save:
            from data.alphavantage_client import _fetch
            with pytest.raises((ValueError, RuntimeError)):
                _fetch("INCOME_STATEMENT", "NVDA")

    def test_returns_data_on_success(self, monkeypatch):
        monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "test-key")
        payload = {"annualReports": [_income_row()]}
        with patch("data.alphavantage_client.requests.get", return_value=_mock_get(payload)), \
             patch("data.alphavantage_client._rate_limiter.wait"), \
             _no_cache, _no_save:
            from data.alphavantage_client import _fetch
            result = _fetch("INCOME_STATEMENT", "NVDA")
        assert "annualReports" in result
        assert len(result["annualReports"]) == 1


# ── _to_dataframe ─────────────────────────────────────────────────────────────

class TestToDataframe:
    def test_returns_dataframe_with_required_cols(self):
        from data.alphavantage_client import _to_dataframe, _INCOME_COLS

        rows = [_income_row(f"202{i}-01-28") for i in range(5, 0, -1)]
        df = _to_dataframe(rows, _INCOME_COLS)

        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == _INCOME_COLS
        assert len(df) == 5

    def test_none_strings_become_na(self):
        from data.alphavantage_client import _to_dataframe, _INCOME_COLS

        row = _income_row()
        row["ebitda"] = "None"
        df = _to_dataframe([row], _INCOME_COLS)

        assert pd.isna(df.iloc[0]["ebitda"])

    def test_missing_column_filled_with_na(self):
        from data.alphavantage_client import _to_dataframe, _INCOME_COLS

        row = {k: v for k, v in _income_row().items() if k != "ebitda"}
        df = _to_dataframe([row], _INCOME_COLS)

        assert "ebitda" in df.columns
        assert pd.isna(df.iloc[0]["ebitda"])

    def test_truncates_to_n_years(self):
        from data.alphavantage_client import _to_dataframe, _INCOME_COLS

        rows = [_income_row(f"202{i}-01-28") for i in range(8, 0, -1)]
        df = _to_dataframe(rows, _INCOME_COLS, n_years=5)

        assert len(df) == 5

    def test_numeric_conversion(self):
        from data.alphavantage_client import _to_dataframe, _INCOME_COLS

        df = _to_dataframe([_income_row()], _INCOME_COLS)
        assert df.iloc[0]["totalRevenue"] == pytest.approx(130_497_000_000)


# ── get_income_statement ──────────────────────────────────────────────────────

class TestGetIncomeStatement:
    def test_returns_dataframe(self, monkeypatch):
        monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "test-key")
        rows = [_income_row(f"202{i}-01-28") for i in range(5, 0, -1)]
        payload = _av_response(rows)

        with patch("data.alphavantage_client.requests.get",
                   return_value=_mock_get(payload)), \
             patch("data.alphavantage_client._rate_limiter.wait"), \
             patch("data.alphavantage_client._load_cache", return_value=None), \
             patch("data.alphavantage_client._save_cache"):
            from data.alphavantage_client import get_income_statement
            df = get_income_statement("NVDA")

        assert isinstance(df, pd.DataFrame)
        assert "totalRevenue" in df.columns
        assert len(df) == 5

    def test_raises_when_no_reports(self, monkeypatch):
        monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "test-key")
        payload = {"annualReports": []}

        with patch("data.alphavantage_client.requests.get",
                   return_value=_mock_get(payload)), \
             patch("data.alphavantage_client._rate_limiter.wait"), \
             patch("data.alphavantage_client._load_cache", return_value=None), \
             patch("data.alphavantage_client._save_cache"):
            from data.alphavantage_client import get_income_statement
            with pytest.raises(ValueError, match="No annual income"):
                get_income_statement("NVDA")
