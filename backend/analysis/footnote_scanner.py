"""
Footnote risk scanner — sweeps a 10-K's RAG index for 6 risk categories
and classifies each signal via Claude (temperature=0).
"""
import json
import logging
import os
import re
import time
from typing import Any

import anthropic
import chromadb

logger = logging.getLogger(__name__)

# ── Risk category definitions ──────────────────────────────────────────────

_CATEGORIES: list[dict[str, Any]] = [
    {
        "id": "going_concern",
        "label": "Going Concern Risk",
        "queries": [
            "going concern doubt ability to continue operations",
            "auditor emphasis of matter substantial doubt",
            "liquidity risk cash runway operating losses",
        ],
    },
    {
        "id": "customer_concentration",
        "label": "Customer Concentration",
        "queries": [
            "major customer revenue percentage concentration",
            "significant customer accounts receivable percent",
            "customer concentration risk single largest customer",
        ],
    },
    {
        "id": "litigation",
        "label": "Litigation and Contingent Liabilities",
        "queries": [
            "litigation legal proceedings lawsuit settlement",
            "contingent liabilities reserve accrual material",
            "regulatory investigation enforcement action penalty",
        ],
    },
    {
        "id": "accounting_changes",
        "label": "Accounting Policy Changes",
        "queries": [
            "change in accounting policy revenue recognition method",
            "change in depreciation amortization method estimate",
            "adoption of new accounting standard ASC IFRS impact",
        ],
    },
    {
        "id": "goodwill_impairment",
        "label": "Goodwill and Intangibles",
        "queries": [
            "goodwill impairment test discount rate assumptions",
            "goodwill impairment charge reporting unit fair value",
            "indefinite-lived intangibles impairment growth rate",
        ],
    },
    {
        "id": "related_party",
        "label": "Related Party Transactions",
        "queries": [
            "related party transactions arm's length pricing",
            "transactions with officers directors affiliates",
            "related party revenue loans independence statement",
        ],
    },
]

_SYSTEM_PROMPT = (
    "You are a forensic financial analyst. "
    "You MUST respond with valid JSON only — no markdown fences, no prose. "
    "Every signal you report must include a page number citation from the excerpts. "
    "If the excerpts contain no relevant signals, return {\"signals\": []}."
)

_USER_TEMPLATE = """\
You are analyzing {category} risk in this 10-K filing for {ticker} ({year}).

Based on the following excerpts from the financial notes, identify any risk signals.
For each signal found, classify it as one of:
  "critical" — ⚠ needs immediate attention
  "monitor"  — △ worth tracking
  "normal"   — ✓ no anomaly

Respond in this EXACT JSON format (no other text):
{{
  "signals": [
    {{
      "title": "max 15 words",
      "level": "critical|monitor|normal",
      "explanation": "2-3 sentences: what this means, why it matters, severity",
      "note_reference": "Note X, page Y",
      "excerpt": "exact quote from source, max 50 words"
    }}
  ]
}}

Only include signals actually present in the excerpts. Return empty signals array if none found.

Excerpts:
{context}
"""


# ── Claude call ────────────────────────────────────────────────────────────

def _claude_create(client: anthropic.Anthropic, **kwargs) -> anthropic.types.Message:
    """One retry with a short wait. Caller handles graceful degradation on failure."""
    try:
        return client.messages.create(**kwargs)
    except (anthropic.RateLimitError, anthropic.APIStatusError) as exc:
        status = getattr(exc, "status_code", 0)
        if status not in (429, 500, 503, 529):
            raise
        logger.warning("Anthropic %s — retrying once in 10s", status or "rate-limit")
        time.sleep(10)
        return client.messages.create(**kwargs)


def _call_claude(prompt: str, api_key: str) -> list[dict]:
    client = anthropic.Anthropic(api_key=api_key, max_retries=0)
    message = _claude_create(
        client,
        model="claude-sonnet-4-6",
        max_tokens=2048,
        temperature=0,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()

    # Strip accidental markdown fences if model adds them
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        parsed = json.loads(raw)
        return parsed.get("signals", [])
    except json.JSONDecodeError as exc:
        logger.warning("JSON parse failed for Claude response: %s\nRaw: %.200s", exc, raw)
        return []


# ── RAG retrieval for one category ────────────────────────────────────────

def _retrieve_context(
    collection: chromadb.Collection,
    queries: list[str],
    n_per_query: int = 4,
) -> str:
    """Run multiple queries and merge deduplicated top results into a context block."""
    seen_ids: set[str] = set()
    blocks: list[str] = []

    for query in queries:
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
            blocks.append(f"[{section}, Page {page}]\n{doc}")

    return "\n\n---\n\n".join(blocks)


# ── Deduplication ──────────────────────────────────────────────────────────

def _dedup(signals: list[dict]) -> list[dict]:
    """Remove duplicate signals by (category_id, note_reference, level)."""
    seen: set[tuple] = set()
    out: list[dict] = []
    for s in signals:
        key = (s.get("category_id"), s.get("note_reference", ""), s.get("title", ""))
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


# ── Public API ─────────────────────────────────────────────────────────────

def scan_all_footnotes(
    collection: chromadb.Collection,
    ticker: str,
    year: str,
) -> list[dict[str, Any]]:
    """
    Scan all 6 risk categories against the RAG index.
    Returns a deduplicated flat list of signal dicts, each annotated with
    `category_id` and `category_label`.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY environment variable not set")

    all_signals: list[dict[str, Any]] = []

    for cat in _CATEGORIES:
        logger.info("Scanning category: %s", cat["label"])
        print(f"  → Scanning: {cat['label']} ...", flush=True)

        context = _retrieve_context(collection, cat["queries"])
        if not context.strip():
            logger.info("  No context retrieved for %s — skipping", cat["label"])
            continue

        prompt = _USER_TEMPLATE.format(
            category=cat["label"],
            ticker=ticker.upper(),
            year=year,
            context=context,
        )

        try:
            signals = _call_claude(prompt, api_key)
        except anthropic.APIStatusError as exc:
            logger.warning("Anthropic unavailable for %s (skipping): %s", cat["label"], exc)
            signals = []
        except Exception as exc:
            logger.warning("Claude call failed for %s (skipping): %s", cat["label"], exc)
            signals = []

        for s in signals:
            s["category_id"] = cat["id"]
            s["category_label"] = cat["label"]

        logger.info("  Found %d signal(s) for %s", len(signals), cat["label"])
        all_signals.extend(signals)

        # Respect Claude rate limits between categories
        time.sleep(0.5)

    return _dedup(all_signals)
