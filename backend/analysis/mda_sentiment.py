"""
MD&A management-tone sentiment analysis.

Retrieves the Management Discussion & Analysis section from the RAG index,
then asks Claude to score the overall tone on a -1 → +1 scale and extract
the key forward-looking themes.

Returns a structured dict consumed by the report API and Excel workbook.
"""
import json
import logging
import os
import re
from typing import Any

import anthropic
import chromadb

logger = logging.getLogger(__name__)

# ── Retrieval queries ─────────────────────────────────────────────────────────

_MDA_QUERIES = [
    "management discussion analysis results of operations revenue growth",
    "forward looking outlook guidance fiscal year expectations",
    "management commentary risk factors challenges opportunities",
    "operating results performance highlights key metrics",
    "liquidity capital resources cash flow management perspective",
]

_SYSTEM_PROMPT = (
    "You are a buy-side financial analyst specializing in qualitative earnings analysis. "
    "You MUST respond with valid JSON only — no markdown fences, no prose. "
    "Base your analysis solely on the provided excerpts."
)

_USER_TEMPLATE = """\
Analyze the management tone in the MD&A section of the {ticker} {year} 10-K filing.

Using ONLY the excerpts below, evaluate:
1. The overall management tone (bullish, cautiously optimistic, neutral, cautiously pessimistic, bearish)
2. A numeric sentiment score from -1.0 (very bearish) to +1.0 (very bullish)
3. Up to 5 forward-looking themes or key phrases that justify your score
4. A one-sentence summary of management's narrative

Respond in this EXACT JSON format (no other text):
{{
  "tone": "bullish|cautiously optimistic|neutral|cautiously pessimistic|bearish",
  "score": <float between -1.0 and 1.0>,
  "themes": [
    {{
      "theme": "max 8 words",
      "sentiment": "positive|neutral|negative",
      "excerpt": "exact quote max 40 words"
    }}
  ],
  "summary": "one sentence describing management narrative"
}}

Excerpts:
{context}
"""


# ── Retrieval ─────────────────────────────────────────────────────────────────

def _retrieve_mda_context(collection: chromadb.Collection, n_per_query: int = 5) -> str:
    """Query the RAG index for MD&A passages, preferring chunks labelled 'MD&A'."""
    seen_ids: set[str] = set()
    # Buckets: MD&A-labelled chunks first, then everything else
    mda_blocks: list[str] = []
    other_blocks: list[str] = []

    for query in _MDA_QUERIES:
        results = collection.query(
            query_texts=[query],
            n_results=n_per_query,
            include=["documents", "metadatas"],
        )
        docs: list[str] = results["documents"][0]
        metas: list[dict] = results["metadatas"][0]
        ids: list[str] = results["ids"][0]

        for doc_id, doc, meta in zip(ids, docs, metas):
            if doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)
            section = meta.get("section", "Unknown")
            page = meta.get("page_number", "?")
            block = f"[{section}, Page {page}]\n{doc}"
            if "md&a" in section.lower() or "management" in section.lower():
                mda_blocks.append(block)
            else:
                other_blocks.append(block)

    # Lead with MD&A-labelled content; cap total to avoid token bloat
    combined = mda_blocks + other_blocks
    return "\n\n---\n\n".join(combined[:20])


# ── Claude call ───────────────────────────────────────────────────────────────

def _claude_create(client: anthropic.Anthropic, **kwargs) -> anthropic.types.Message:
    """One retry with a short wait. Caller handles graceful degradation on failure."""
    import time as _time
    try:
        return client.messages.create(**kwargs)
    except (anthropic.RateLimitError, anthropic.APIStatusError) as exc:
        status = getattr(exc, "status_code", 0)
        if status not in (429, 500, 503, 529):
            raise
        logger.warning("Anthropic %s — retrying once in 10s", status or "rate-limit")
        _time.sleep(10)
        return client.messages.create(**kwargs)


def _call_claude(prompt: str, api_key: str) -> dict[str, Any]:
    client = anthropic.Anthropic(api_key=api_key, max_retries=0)
    message = _claude_create(
        client,
        model="claude-sonnet-4-6",
        max_tokens=1024,
        temperature=0,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()

    # Strip accidental markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    return json.loads(raw)


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_mda_sentiment(
    collection: chromadb.Collection,
    ticker: str,
    year: str,
) -> dict[str, Any]:
    """
    Retrieve MD&A passages from the RAG index and score management tone via Claude.

    Returns:
        {
            "ticker": str,
            "year": str,
            "tone": str,          # e.g. "bullish"
            "score": float,       # -1.0 → +1.0
            "themes": [...],      # up to 5 theme dicts
            "summary": str,       # one-sentence narrative
        }

    Raises EnvironmentError if ANTHROPIC_API_KEY is not set.
    Falls back to a neutral result with a descriptive note if the Claude
    response cannot be parsed (malformed JSON, unexpected schema).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY environment variable not set")

    context = _retrieve_mda_context(collection)
    if not context.strip():
        logger.warning("No MD&A context retrieved for %s %s — returning neutral", ticker, year)
        return {
            "ticker": ticker,
            "year": year,
            "tone": "neutral",
            "score": 0.0,
            "themes": [],
            "summary": "No MD&A text could be retrieved from the filing index.",
        }

    prompt = _USER_TEMPLATE.format(
        ticker=ticker.upper(),
        year=year,
        context=context,
    )

    try:
        result = _call_claude(prompt, api_key)
    except Exception as exc:
        logger.warning("MD&A sentiment unavailable for %s %s: %s", ticker, year, exc)
        return {
            "ticker": ticker,
            "year": year,
            "tone": "unavailable",
            "score": 0.0,
            "themes": [],
            "summary": "Sentiment analysis skipped — Claude API temporarily unavailable.",
        }

    # Normalise: clamp score, ensure required keys exist
    score = float(result.get("score", 0.0))
    score = max(-1.0, min(1.0, score))

    return {
        "ticker": ticker,
        "year": year,
        "tone": result.get("tone", "neutral"),
        "score": round(score, 3),
        "themes": result.get("themes", []),
        "summary": result.get("summary", ""),
    }
