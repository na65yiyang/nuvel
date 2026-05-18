import os
import sys
from pathlib import Path

# Ensure backend/ is on sys.path regardless of how the worker is launched.
# Required after folder renames that break venv's baked-in paths.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from celery import Celery
from dotenv import load_dotenv

load_dotenv(_BACKEND / ".env")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "nuvel",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks.analysis_tasks", "tasks.test_tasks", "tasks.mock_analysis_task"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    result_expires=86400,
    # macOS: ChromaDB's ONNX runtime initialises Swift/ObjC threads before
    # Celery forks workers, causing SIGABRT. Solo pool runs tasks in-process
    # (no fork). On Linux (Railway) override with --pool=prefork.
    worker_pool="solo",
    broker_connection_retry_on_startup=True,
)
