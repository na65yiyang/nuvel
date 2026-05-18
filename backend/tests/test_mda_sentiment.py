"""
Unit tests for analysis/mda_sentiment.py.
All Anthropic and ChromaDB calls are mocked.
"""
import json
from unittest.mock import MagicMock, patch

import pytest


def _make_collection(docs=None, metas=None, ids=None):
    """Return a ChromaDB collection mock that returns preset query results."""
    docs = docs or ["Management expects strong revenue growth in FY2025."]
    metas = metas or [{"section": "MD&A", "page_number": 42}]
    ids = ids or ["chunk_0"]

    collection = MagicMock()
    collection.query.return_value = {
        "documents": [docs],
        "metadatas": [metas],
        "ids": [ids],
    }
    return collection


def _claude_response(payload: dict) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=json.dumps(payload))]
    return msg


_VALID_RESPONSE = {
    "tone": "bullish",
    "score": 0.78,
    "themes": [
        {
            "theme": "Strong revenue guidance",
            "sentiment": "positive",
            "excerpt": "We expect strong revenue growth driven by AI demand.",
        }
    ],
    "summary": "Management is highly optimistic about AI-driven growth in FY2025.",
}


class TestAnalyzeMdaSentiment:
    def test_returns_structured_dict(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        collection = _make_collection()

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_anthropic.return_value.messages.create.return_value = _claude_response(
                _VALID_RESPONSE
            )
            from analysis.mda_sentiment import analyze_mda_sentiment
            result = analyze_mda_sentiment(collection, "NVDA", "2024")

        assert result["ticker"] == "NVDA"
        assert result["year"] == "2024"
        assert result["tone"] == "bullish"
        assert result["score"] == pytest.approx(0.78)
        assert len(result["themes"]) == 1

    def test_score_clamped_to_range(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        collection = _make_collection()
        extreme = {**_VALID_RESPONSE, "score": 9.99}

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_anthropic.return_value.messages.create.return_value = _claude_response(extreme)
            from analysis.mda_sentiment import analyze_mda_sentiment
            result = analyze_mda_sentiment(collection, "NVDA", "2024")

        assert result["score"] <= 1.0

    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        collection = _make_collection()
        from analysis.mda_sentiment import analyze_mda_sentiment
        with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
            analyze_mda_sentiment(collection, "NVDA", "2024")

    def test_neutral_fallback_on_empty_context(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        # Return empty lists so no blocks are built and context is empty
        collection = MagicMock()
        collection.query.return_value = {"documents": [[]], "metadatas": [[]], "ids": [[]]}

        from analysis.mda_sentiment import analyze_mda_sentiment
        result = analyze_mda_sentiment(collection, "AAPL", "2024")

        assert result["tone"] in ("neutral", "unavailable")
        assert result["score"] == 0.0

    def test_neutral_fallback_on_bad_json(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        collection = _make_collection()
        bad_msg = MagicMock()
        bad_msg.content = [MagicMock(text="not json at all")]

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_anthropic.return_value.messages.create.return_value = bad_msg
            from analysis.mda_sentiment import analyze_mda_sentiment
            result = analyze_mda_sentiment(collection, "NVDA", "2024")

        assert result["tone"] in ("neutral", "unavailable")
        assert result["score"] == 0.0
