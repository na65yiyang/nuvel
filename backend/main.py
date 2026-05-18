from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.routes import router
from tasks.test_tasks import add

app = FastAPI(title="Nuvel API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}


class AddPayload(BaseModel):
    a: float
    b: float


@app.post("/api/test-task")
async def test_task(payload: AddPayload):
    result = add.delay(payload.a, payload.b)
    return {"task_id": result.id}


@app.get("/api/test-task/{task_id}")
async def get_task_result(task_id: str):
    from tasks.celery_app import celery_app

    result = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "state": result.state,
        "result": result.result if result.ready() else None,
    }
