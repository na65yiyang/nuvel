"""
Full 10-K analysis pipeline as a Celery task.
Broadcasts a Redis Pub/Sub progress event after every step.
"""
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

# Guarantee backend/ is on sys.path in forked Celery worker processes.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import pandas as pd
import redis

from tasks.celery_app import celery_app

from data.edgar_client import download_filing_pdf, get_latest_filing_url
from data.alphavantage_client import get_all_statements
from analysis.rag_pipeline import build_index
from analysis.footnote_scanner import scan_all_footnotes
from analysis.mda_sentiment import analyze_mda_sentiment
from excel.workbook_generator import generate_workbook

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

_STEPS = [
    (1, "Fetch 10-K from SEC EDGAR"),
    (2, "Parse financial statements"),
    (3, "Calculate financial ratios"),
    (4, "Build RAG vector index"),
    (5, "Scan footnotes for risk signals"),
    (6, "MD&A sentiment analysis"),
    (7, "Generate Excel workbook"),
]


# ── Progress broadcasting ──────────────────────────────────────────────────

def _broadcast(
    r: redis.Redis,
    task_id: str,
    step: int,
    step_name: str,
    status: str,
    detail: str,
    start: float,
) -> None:
    event = {
        "task_id": task_id,
        "step": step,
        "step_name": step_name,
        "status": status,
        "detail": detail,
        "elapsed_seconds": round(time.monotonic() - start, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    r.publish(f"task:{task_id}", json.dumps(event))
    logger.info("[%s] step=%d/%d %-9s %s", task_id, step, 7, status, detail[:80])


def _abs_capex(row_c) -> float | None:
    """AlphaVantage reports capitalExpenditures as a negative cash outflow; return abs value."""
    raw = row_c.get("capitalExpenditures")
    try:
        return abs(float(raw)) if raw is not None and not pd.isna(float(raw)) else None
    except (TypeError, ValueError):
        return None


def _free_cash_flow(row_c) -> float | None:
    """Use freeCashFlow field when present; fall back to operatingCashflow - abs(capex)."""
    fcf_raw = row_c.get("freeCashFlow")
    try:
        fcf = float(fcf_raw)
        if not pd.isna(fcf):
            return fcf
    except (TypeError, ValueError):
        pass
    op_cf_raw = row_c.get("operatingCashflow")
    try:
        op_cf = float(op_cf_raw)
        if pd.isna(op_cf):
            return None
        capex = _abs_capex(row_c) or 0.0
        return op_cf - capex
    except (TypeError, ValueError):
        return None


def _calculate_ratios(statements: dict) -> dict[str, Any]:
    """Computes 15 financial ratios from the three AlphaVantage statements."""
    income = statements["income"]
    balance = statements["balance"]
    cashflow = statements["cashflow"]

    def safe(num, den):
        try:
            result = round(float(num) / float(den), 4) if den and float(den) != 0 else None
            # nan / inf are not JSON-serialisable — treat as missing
            if result is not None and (result != result or result == float("inf")):
                return None
            return result
        except (TypeError, ValueError):
            return None

    row_i = income.iloc[0]
    row_b = balance.iloc[0]
    row_c = cashflow.iloc[0]

    return {
        "gross_margin": safe(row_i.get("grossProfit"), row_i.get("totalRevenue")),
        "operating_margin": safe(row_i.get("operatingIncome"), row_i.get("totalRevenue")),
        "net_margin": safe(row_i.get("netIncome"), row_i.get("totalRevenue")),
        "roa": safe(row_i.get("netIncome"), row_b.get("totalAssets")),
        "roe": safe(row_i.get("netIncome"), row_b.get("totalShareholderEquity")),
        "current_ratio": safe(row_b.get("totalCurrentAssets"), row_b.get("totalCurrentLiabilities")),
        "debt_to_equity": safe(row_b.get("longTermDebt"), row_b.get("totalShareholderEquity")),
        "asset_turnover": safe(row_i.get("totalRevenue"), row_b.get("totalAssets")),
        "rd_to_revenue": safe(row_i.get("researchAndDevelopment"), row_i.get("totalRevenue")),
        "sga_to_revenue": safe(row_i.get("sellingGeneralAndAdministrative"), row_i.get("totalRevenue")),
        "fcf": _free_cash_flow(row_c),
        "capex_to_revenue": safe(_abs_capex(row_c), row_i.get("totalRevenue")),
        "goodwill_to_assets": safe(row_b.get("goodwill"), row_b.get("totalAssets")),
        "receivables_to_revenue": safe(row_b.get("currentNetReceivables"), row_i.get("totalRevenue")),
        "cash_ratio": safe(
            row_b.get("cashAndCashEquivalentsAtCarryingValue"),
            row_b.get("totalCurrentLiabilities"),
        ),
    }




def _generate_excel(
    ticker: str,
    year: str,
    statements: dict,
    ratios: dict,
    signals: list,
) -> str:
    """Generate the 5-sheet Excel workbook and persist it to /tmp."""
    wb_bytes = generate_workbook(
        ticker=ticker,
        year=year,
        income_df=statements["income"],
        balance_df=statements["balance"],
        cashflow_df=statements["cashflow"],
        ratios=ratios,
        signals=signals,
    )
    path = f"/tmp/{ticker.upper()}_10K_{year}_Nuvel.xlsx"
    with open(path, "wb") as fh:
        fh.write(wb_bytes)
    return path


# ── Main Celery task ───────────────────────────────────────────────────────

@celery_app.task(bind=True, name="tasks.run_analysis")
def run_analysis(self, ticker: str, year: str, task_id: str | None = None) -> dict:
    """
    Execute the 7-step 10-K analysis pipeline, broadcasting a Redis Pub/Sub
    progress event after every step.

    Args:
        ticker:  Stock ticker symbol (e.g., "NVDA")
        year:    Fiscal year string (e.g., "2024")
        task_id: Unique ID used as Redis channel name task:{task_id}.
                 Defaults to the Celery task ID.
    """
    if task_id is None:
        task_id = self.request.id or str(uuid.uuid4())

    r = redis.from_url(REDIS_URL, decode_responses=True)
    start = time.monotonic()
    filing_type = "10-K"

    # Track current step so the except block can emit the right step number
    _step: list[int] = [0]
    _step_name: list[str] = [""]

    def emit(step: int, name: str, status: str, detail: str) -> None:
        _step[0] = step
        _step_name[0] = name
        _broadcast(r, task_id, step, name, status, detail, start)

    try:
        # ── Step 1: Fetch 10-K ─────────────────────────────────────────────
        emit(1, _STEPS[0][1], "running", f"Resolving {ticker} 10-K on SEC EDGAR…")
        filing_url = get_latest_filing_url(ticker, filing_type)
        pdf_path = download_filing_pdf(filing_url, ticker, year)
        emit(1, _STEPS[0][1], "completed", f"Downloaded → {pdf_path}")

        # ── Step 2: Parse financial statements ─────────────────────────────
        emit(2, _STEPS[1][1], "running", f"Fetching AlphaVantage statements for {ticker}…")
        statements = get_all_statements(ticker)
        shapes = {k: list(df.shape) for k, df in statements.items()}
        emit(2, _STEPS[1][1], "completed", f"Shapes: {shapes}")

        # ── Step 3: Calculate financial ratios ─────────────────────────────
        emit(3, _STEPS[2][1], "running", "Computing 15 financial ratios…")
        ratios = _calculate_ratios(statements)
        non_null = sum(1 for v in ratios.values() if v is not None)
        emit(3, _STEPS[2][1], "completed", f"Computed {non_null}/15 ratios")

        # ── Step 4: Build RAG vector index ─────────────────────────────────
        emit(4, _STEPS[3][1], "running", "Building ChromaDB vector index…")
        collection = build_index(pdf_path, ticker, year, filing_type)
        emit(4, _STEPS[3][1], "completed", f"Indexed {collection.count()} chunks")

        # ── Step 5: Scan footnotes ─────────────────────────────────────────
        emit(5, _STEPS[4][1], "running", "Scanning 6 footnote risk categories…")
        try:
            signals = scan_all_footnotes(collection, ticker, year)
            critical = sum(1 for s in signals if s.get("level") == "critical")
            monitor = sum(1 for s in signals if s.get("level") == "monitor")
            emit(5, _STEPS[4][1], "completed",
                 f"{len(signals)} signals: {critical} critical, {monitor} monitor")
        except Exception as exc:
            logger.warning("Footnote scan failed (continuing): %s", exc)
            signals = []
            emit(5, _STEPS[4][1], "completed", "Skipped — Claude API unavailable")

        # ── Step 6: MD&A sentiment ─────────────────────────────────────────
        emit(6, _STEPS[5][1], "running", "Analyzing MD&A management tone…")
        try:
            sentiment = analyze_mda_sentiment(collection, ticker, year)
            tone_label = sentiment.get("tone", "neutral").capitalize()
            score = sentiment.get("score", 0.0)
            emit(6, _STEPS[5][1], "completed", f"Tone: {tone_label} (score {score:+.2f})")
        except Exception as exc:
            logger.warning("Sentiment analysis failed (continuing): %s", exc)
            sentiment = {"tone": "unavailable", "score": 0.0, "themes": [], "summary": ""}
            emit(6, _STEPS[5][1], "completed", "Skipped — Claude API unavailable")

        # ── Step 7: Generate Excel workbook ───────────────────────────────
        emit(7, _STEPS[6][1], "running", "Building Excel workbook…")
        excel_path = _generate_excel(ticker, year, statements, ratios, signals)
        emit(7, _STEPS[6][1], "completed", f"Saved → {excel_path}")

        result = {
            "ticker": ticker,
            "year": year,
            "filing_type": filing_type,
            "status": "complete",
            "ratios": ratios,
            "signals": signals,
            "sentiment": sentiment,
            "excel_path": excel_path,
        }

        # Persist so the report endpoint can serve it without the Celery task ID.
        # Use a custom encoder that converts nan/inf → null so the file is valid JSON.
        class _SafeEncoder(json.JSONEncoder):
            def iterencode(self, o, _one_shot=False):
                return super().iterencode(self._sanitise(o), _one_shot)
            def _sanitise(self, obj):
                if isinstance(obj, float):
                    return None if (obj != obj or obj == float("inf") or obj == float("-inf")) else obj
                if isinstance(obj, dict):
                    return {k: self._sanitise(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [self._sanitise(v) for v in obj]
                return obj

        result_path = f"/tmp/{ticker.upper()}_10K_{year}_result.json"
        with open(result_path, "w") as fh:
            json.dump(result, fh, cls=_SafeEncoder)
        logger.info("Result saved → %s", result_path)

        return result

    except Exception as exc:
        logger.exception("Pipeline failed for %s/%s at step %d", ticker, year, _step[0])
        emit(_step[0], _step_name[0], "failed", str(exc))
        raise
