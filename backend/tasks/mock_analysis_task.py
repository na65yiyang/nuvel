"""
Mock pipeline task — walks all 7 steps with realistic delays and no API keys.
Used for integration testing the WebSocket loading page.
"""
import json
import time
import uuid
from datetime import datetime, timezone

import redis

from tasks.celery_app import celery_app

REDIS_URL = __import__("os").getenv("REDIS_URL", "redis://localhost:6379/0")

_MOCK_STEPS = [
    (1, "Fetch 10-K from SEC EDGAR",       1.2, "Downloaded → /tmp/NVDA_2024.html (4.1 MB, 312 pages)"),
    (2, "Parse financial statements",       0.8, "Shapes: income=(5, 42)  balance=(5, 38)  cashflow=(5, 20)"),
    (3, "Calculate financial ratios",       0.4, "Computed 15/15 ratios"),
    (4, "Build RAG vector index",           2.5, "Indexed 1,847 chunks across 6 filing sections"),
    (5, "Scan footnotes for risk signals",  3.0, "8 signals: 1 critical, 4 monitor, 3 normal"),
    (6, "MD&A sentiment analysis",          1.0, "FY2024 tone: Bullish (0.82)  5-year trend: ↑"),
    (7, "Generate Excel workbook",          0.6, "Saved → /tmp/NVDA_10K_2024_Nuvel.xlsx (5 sheets)"),
]


def _broadcast(r, task_id, step, step_name, status, detail, start):
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


@celery_app.task(bind=True, name="tasks.run_mock_analysis")
def run_mock_analysis(self, ticker: str, year: str, task_id: str | None = None):
    if task_id is None:
        task_id = self.request.id or str(uuid.uuid4())

    r = redis.from_url(REDIS_URL, decode_responses=True)
    start = time.monotonic()

    for step, name, delay, detail in _MOCK_STEPS:
        _broadcast(r, task_id, step, name, "running",
                   f"[mock] Starting {name.lower()}…", start)
        time.sleep(delay)
        _broadcast(r, task_id, step, name, "completed", f"[mock] {detail}", start)

    return {"ticker": ticker, "year": year, "mock": True}
