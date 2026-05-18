# Nuvel — AI-Powered Earnings Analysis Platform

Analyze SEC 10-K/10-Q filings with AI. Extracts risk signals, tracks management tone,
calculates financial ratios, and generates a cited Excel workbook.

## Prerequisites

- Docker + Docker Compose
- Node.js 18+
- Python 3.11+

## Quick Start

### 1. Environment setup

```bash
cp backend/.env.example backend/.env
# Fill in ANTHROPIC_API_KEY, ALPHAVANTAGE_API_KEY, R2_*, SUPABASE_* in backend/.env
```

### 2. Start infrastructure (Redis + backend)

```bash
docker-compose up -d
```

This starts:
- Redis on `localhost:6379`
- FastAPI backend on `http://localhost:8000`
- Celery worker (async task queue)

Verify the backend is up:
```bash
curl http://localhost:8000/health
# → {"status": "ok"}
```

### 3. Start frontend (local dev)

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:3000`.

## Running the backend locally (without Docker)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

In a second terminal (Celery worker):
```bash
cd backend && source .venv/bin/activate
celery -A tasks.celery_app worker --loglevel=info
```

## Project Structure

```
/frontend          → Next.js 14 App Router (TypeScript + Tailwind)
/backend
  /api             → FastAPI route handlers
  /tasks           → Celery task definitions (analysis pipeline)
  /analysis        → AI pipeline modules (RAG, risk signals, sentiment)
  /data            → SEC EDGAR, AlphaVantage, yfinance clients
  /excel           → openpyxl Excel workbook generation
  main.py          → FastAPI app entry point
  requirements.txt
  Dockerfile
/docker-compose.yml
```

## Report URL format

```
nuvel.co/analyze/{TICKER}/{TYPE}/{YEAR}
```

Example: `nuvel.co/analyze/NVDA/10-K/2024`
