"""
Nuvel API routes:
  POST /api/analyze/{ticker}              — start analysis pipeline
  GET  /api/report/{ticker}/{type}/{year} — fetch completed report
  POST /api/ask/{ticker}/{year}           — RAG question answering
  WS   /ws/{task_id}                      — real-time pipeline progress
"""
import json
import logging
import os
import re
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
router = APIRouter()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")

# Rich mock report for UI development (real R2 fetch in a future prompt)
_MOCK_REPORTS: dict = {
    "NVDA": {
        "ticker": "NVDA",
        "company_name": "NVIDIA Corporation",
        "filing_type": "10K",
        "year": "2024",
        "filing_date": "2026-02-25",
        "price": 875.40,
        "market_cap": "2.14T",
        "ratios": {
            "gross_margin":           0.7499,
            "operating_margin":       0.6255,
            "net_margin":             0.5585,
            "roa":                    0.6530,
            "roe":                    1.1088,
            "current_ratio":          3.2926,
            "debt_to_equity":         0.1288,
            "asset_turnover":         1.1693,
            "rd_to_revenue":          0.0990,
            "sga_to_revenue":         0.0254,
            "fcf":               64089000000,
            "capex_to_revenue":       0.0243,
            "goodwill_to_assets":     0.0397,
            "receivables_to_revenue": 0.1329,
            "cash_ratio":             0.4645,
        },
        "ratios_history": {
            "gross_margin":     [0.623, 0.649, 0.569, 0.727, 0.750],
            "operating_margin": [0.272, 0.373, 0.157, 0.541, 0.626],
            "net_margin":       [0.260, 0.362, 0.162, 0.489, 0.559],
            "roe":              [0.257, 0.366, 0.164, 0.692, 1.109],
            "current_ratio":    [3.35,  2.66,  3.32,  4.17,  3.29],
        },
        "signals": [
            {
                "title": "Export controls may restrict GPU sales to China",
                "level": "critical",
                "category_label": "Risk Factors",
                "category_id": "going_concern",
                "explanation": "US government has imposed and may further impose export controls on high-performance GPUs. NVDA has already lost significant China revenue and new rules could further restrict sales. Management cites this as a primary risk to future revenue.",
                "note_reference": "Item 1A, page 24",
                "excerpt": "Export controls could limit alternative manufacturing locations and negatively impact our business. We have experienced and may continue to experience export control restrictions."
            },
            {
                "title": "Securities class action remanded to district court",
                "level": "monitor",
                "category_label": "Litigation",
                "category_id": "litigation",
                "explanation": "A Ninth Circuit securities class action was remanded in February 2025 for further proceedings. No reserve amount is disclosed, suggesting NVDA believes loss is not probable but the case remains open and could result in material costs.",
                "note_reference": "Note 17, page 109",
                "excerpt": "Ninth Circuit judgment took effect February 20, 2025, and the case was remanded to the district court for further proceedings. The putative class period is..."
            },
            {
                "title": "Customer concentration in indirect channel",
                "level": "monitor",
                "category_label": "Customer Concentration",
                "category_id": "customer_concentration",
                "explanation": "A small number of indirect customers (hyperscalers) contribute a disproportionate share of data center revenue. Loss of any major customer would have an outsized impact on quarterly results and guidance.",
                "note_reference": "Note 14, page 76",
                "excerpt": "Indirect customer revenue is an estimation based upon multiple factors including customer purchase order information, product specifications, and internal sales data."
            },
            {
                "title": "Goodwill impairment tested — no charge recorded",
                "level": "normal",
                "category_label": "Goodwill & Intangibles",
                "category_id": "goodwill_impairment",
                "explanation": "NVDA discloses goodwill impairment testing uses discounted future cash flows. No impairment charge recorded in FY2025. Goodwill represents only 4% of total assets, a low-risk level.",
                "note_reference": "Note 7, page 98",
                "excerpt": "Fair value is determined based on the estimated discounted future cash flows expected to be generated by the asset or asset group."
            },
        ],
        "sentiment": [
            {"year": "FY21", "score": 0.58, "label": "Positive"},
            {"year": "FY22", "score": 0.71, "label": "Optimistic"},
            {"year": "FY23", "score": 0.42, "label": "Cautious"},
            {"year": "FY24", "score": 0.79, "label": "Bullish"},
            {"year": "FY25", "score": 0.86, "label": "Very Bullish"},
        ],
        "beat_miss": [
            {"metric": "Revenue", "consensus": "$129.0B", "actual": "$130.5B", "result": "beat", "surprise": "+1.2%"},
            {"metric": "EPS (diluted)", "consensus": "$2.93", "actual": "$2.99", "result": "beat", "surprise": "+2.0%"},
            {"metric": "Gross Margin", "consensus": "73.5%", "actual": "74.6%", "result": "beat", "surprise": "+110 bps"},
            {"metric": "Data Center Rev", "consensus": "$111.0B", "actual": "$115.2B", "result": "beat", "surprise": "+3.8%"},
            {"metric": "Gaming Rev", "consensus": "$11.5B", "actual": "$11.4B", "result": "miss", "surprise": "−0.9%"},
        ],
        "excel_url": "/api/excel/NVDA/10K/2024",
    }
}


def _validate_ticker(ticker: str) -> str:
    t = ticker.strip().upper()
    if not _TICKER_RE.match(t):
        raise HTTPException(status_code=422, detail=f"Invalid ticker: '{ticker}'")
    return t


# ── POST /api/analyze/{ticker} ─────────────────────────────────────────────

@router.post("/api/analyze/{ticker}")
async def start_analysis(ticker: str, year: str = "2024"):
    t = _validate_ticker(ticker)
    task_id = str(uuid.uuid4())
    celery_app.send_task(
        "tasks.run_analysis",
        kwargs={"ticker": t, "year": year, "task_id": task_id},
    )
    return {"task_id": task_id, "ticker": t, "year": year,
            "websocket_url": f"ws://localhost:8000/ws/{task_id}"}


# ── GET /api/report/{ticker}/{type}/{year} ─────────────────────────────────

@router.get("/api/report/{ticker}/{filing_type}/{year}")
async def get_report(ticker: str, filing_type: str, year: str):
    t = _validate_ticker(ticker)

    # 1. Try real result saved by the Celery pipeline
    result_path = f"/tmp/{t}_10K_{year}_result.json"
    if os.path.exists(result_path):
        with open(result_path) as fh:
            return json.load(fh)

    # 2. Fall back to hardcoded mock (NVDA only, for demo without API keys)
    mock = _MOCK_REPORTS.get(t)
    if mock:
        return {**mock, "status": "complete"}

    raise HTTPException(
        status_code=404,
        detail=f"No completed report found for {t} {year}. Run the analysis first.",
    )


# ── POST /api/ask/{ticker}/{year} ──────────────────────────────────────────

class AskPayload(BaseModel):
    question: str


@router.post("/api/ask/{ticker}/{year}")
async def ask_question(ticker: str, year: str, payload: AskPayload):
    """RAG question answering — uses persisted ChromaDB index if available."""
    t = _validate_ticker(ticker)

    # Try to use the real RAG pipeline if index exists
    try:
        import chromadb  # noqa: PLC0415
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2  # noqa: PLC0415
        from analysis.rag_pipeline import query_with_citation  # noqa: PLC0415

        collection_name = f"{t}_{year}_10K"
        persist_path = f"/tmp/chroma_db/{collection_name}"
        client = chromadb.PersistentClient(path=persist_path)
        col = client.get_collection(collection_name, embedding_function=ONNXMiniLM_L6_V2())
        result = query_with_citation(col, payload.question)
        return result
    except Exception:
        pass

    # Fallback placeholder
    return {
        "answer": (
            f"RAG index for {t} {year} is not yet built on this server. "
            "Run a full analysis first via POST /api/analyze/{ticker}."
        ),
        "citations": [],
    }


# ── POST /api/analyze-mock/{ticker} — no API keys needed ──────────────────

@router.post("/api/analyze-mock/{ticker}")
async def start_mock_analysis(ticker: str, year: str = "2024"):
    """
    Fire a mock analysis that walks all 7 pipeline steps using embedded data.
    Useful for WebSocket/loading-page integration tests without real API keys.
    """
    t = _validate_ticker(ticker)
    task_id = str(uuid.uuid4())
    celery_app.send_task(
        "tasks.run_mock_analysis",
        kwargs={"ticker": t, "year": year, "task_id": task_id},
    )
    return {"task_id": task_id, "ticker": t, "year": year,
            "websocket_url": f"ws://localhost:8000/ws/{task_id}"}


# ── GET /api/excel/{ticker}/{type}/{year} ──────────────────────────────────

@router.get("/api/excel/{ticker}/{filing_type}/{year}")
async def get_excel(ticker: str, filing_type: str, year: str):
    """
    Return an Excel workbook (.xlsx) for the given filing.
    Priority:
      1. Pre-generated file dropped by the Celery task at /tmp/{TICKER}_10K_{year}_Nuvel.xlsx
      2. On-demand workbook built from embedded NVDA mock data (development fallback)
    """
    t = _validate_ticker(ticker)
    ft = filing_type.upper().replace("-", "")
    fname = f"{t}_{ft}_{year}_Nuvel.xlsx"

    # ── Try cached file from completed Celery task ─────────────────────────
    cached = f"/tmp/{t}_10K_{year}_Nuvel.xlsx"
    if os.path.exists(cached):
        with open(cached, "rb") as fh:
            content = fh.read()
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    # ── On-demand generation using NVDA mock data ──────────────────────────
    try:
        import pandas as pd  # noqa: PLC0415
        from excel.workbook_generator import generate_workbook  # noqa: PLC0415

        mock = _MOCK_REPORTS.get(t, {})

        # Five years of NVDA financials (newest row first, matching AlphaVantage layout)
        income_df = pd.DataFrame({
            "fiscalDateEnding": ["2024-01-28", "2023-01-29", "2022-01-30", "2021-01-31", "2020-01-26"],
            "totalRevenue":                  [130497000000, 60922000000, 26974000000, 16675000000, 10918000000],
            "grossProfit":                   [ 97796000000, 39553000000, 15356000000, 10208000000,  6539000000],
            "operatingIncome":               [ 81614000000, 32972000000,  4224000000,  4532000000,  2846000000],
            "netIncome":                     [ 72880000000, 29760000000,  4368000000,  4332000000,  2796000000],
            "researchAndDevelopment":        [ 12908000000,  7339000000,  7953000000,  5268000000,  3924000000],
            "sellingGeneralAndAdministrative":[  3332000000,  2440000000,  2166000000,  1940000000,  2016000000],
            "ebitda":                        [ 85000000000, 34000000000,  5000000000,  5000000000,  3500000000],
            "eps":                           [        2.99,        1.19,       0.174,       0.174,       0.113],
        })
        balance_df = pd.DataFrame({
            "fiscalDateEnding": ["2024-01-28", "2023-01-29", "2022-01-30", "2021-01-31", "2020-01-26"],
            "totalAssets":                            [111601000000, 65728000000, 44187000000, 28791000000, 17315000000],
            "totalCurrentAssets":                     [ 79944000000, 44345000000, 28829000000, 17188000000, 10277000000],
            "totalCurrentLiabilities":                [ 24298000000, 10289000000,  7536000000,  4345000000,  2920000000],
            "longTermDebt":                           [  8461000000,  9703000000, 10929000000,  5964000000,  1987000000],
            "totalShareholderEquity":                 [ 65728000000, 42978000000, 26612000000, 16893000000, 12204000000],
            "cashAndCashEquivalentsAtCarryingValue":  [  8589000000,  3614000000,  1990000000,   847000000,  1100000000],
            "currentNetReceivables":                  [ 17319000000,  7764000000,  7764000000,  2429000000,  1657000000],
            "inventory":                              [  1640000000,  4319000000,  2686000000,  2111000000,   979000000],
            "goodwill":                               [  4430000000,  4430000000,  4349000000,  4349000000,   616000000],
        })
        cashflow_df = pd.DataFrame({
            "fiscalDateEnding": ["2024-01-28", "2023-01-29", "2022-01-30", "2021-01-31", "2020-01-26"],
            "operatingCashflow":   [71776000000, 28608000000, 9108000000, 5822000000, 4761000000],
            "capitalExpenditures": [ 3169000000,  1833000000,  976000000,  214000000,  489000000],
            "freeCashFlow":        [64089000000, 26775000000, 8132000000, 5608000000, 4272000000],
        })

        wb_bytes = generate_workbook(
            ticker=t,
            year=year,
            income_df=income_df,
            balance_df=balance_df,
            cashflow_df=cashflow_df,
            ratios=mock.get("ratios", {}),
            signals=mock.get("signals", []),
            filing_date=mock.get("filing_date", ""),
        )
        return Response(
            content=wb_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    except Exception as exc:
        logger.exception("Excel generation failed for %s/%s/%s", t, ft, year)
        raise HTTPException(status_code=500, detail=f"Excel generation failed: {exc}") from exc


# ── WebSocket /ws/{task_id} ────────────────────────────────────────────────

@router.websocket("/ws/{task_id}")
async def ws_task_progress(websocket: WebSocket, task_id: str):
    await websocket.accept()
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()
    channel = f"task:{task_id}"
    try:
        await pubsub.subscribe(channel)
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            data = json.loads(message["data"])
            await websocket.send_json(data)
            if data.get("status") in ("completed", "failed"):
                if data.get("status") == "failed" or data.get("step") == 7:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WebSocket error on %s: %s", channel, exc)
    finally:
        await pubsub.unsubscribe(channel)
        await r.aclose()
        try:
            await websocket.close()
        except Exception:
            pass
