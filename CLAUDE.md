# Nuvel — AI-Powered Earnings Analysis Platform

## What This Product Does
Nuvel helps retail investors analyze SEC filings (10-K annual reports, 10-Q quarterly reports)
using AI. It extracts risk signals from financial footnotes, tracks management tone over time,
calculates financial ratios, and generates an auditable Excel workbook with full source citations.

## Tech Stack
### Frontend
- Next.js 14 (App Router)
- Tailwind CSS
- Recharts (financial charts)
- TanStack Query (data fetching + caching)
- Framer Motion (loading animations)
- Native WebSocket (real-time progress)
- Deployed on Vercel

### Backend
- Python, FastAPI (REST + WebSocket)
- Celery + Redis (async task queue)
- pandas (financial data processing)
- openpyxl (Excel generation)
- Deployed on Railway with Docker

### AI & Data Layer
- Claude API: temperature=0, max_tokens=2048. ALL analysis must include source citations.
- LangChain: RAG pipeline with RetrievalQAChain
- ChromaDB: vector index, collection naming = {ticker}_{year}_{type}
- AlphaVantage: financial statements. Free tier = 5 req/min. Always use exponential backoff.
- SEC EDGAR: companyfacts API (XBRL data) + submissions API (filing list)
- Yahoo Finance (yfinance): analyst consensus estimates, real-time price

### Storage
- Cloudflare R2: report JSON, Excel files, 10-K PDFs
- Supabase PostgreSQL: report metadata, user table, query logs
- Redis: Celery broker + hot cache + WebSocket state

## Project Structure
```
/frontend          → Next.js app
/backend
  /api             → FastAPI routes
  /tasks           → Celery task definitions
  /analysis        → AI pipeline modules
  /data            → Data fetching clients
  /excel           → openpyxl Excel generation
/docker-compose.yml
```

## Non-Negotiable Rules
1. Every number in the Excel output must have a source citation (page number + data source)
2. Every Claude API call must have temperature=0
3. AlphaVantage calls must always include exponential backoff retry logic
4. All analysis results must be JSON-serializable and stored in Cloudflare R2
5. WebSocket progress events must be broadcast after EVERY completed pipeline step

## Analysis Pipeline Steps (10-K)
1. Fetch 10-K from SEC EDGAR → cache PDF to R2
2. Parse financial statements via AlphaVantage → pandas TTM normalization
3. Calculate 15 financial ratios
4. Build RAG vector index (ChromaDB)
5. Scan footnotes for 6 risk signal categories → Claude API
6. MD&A sentiment analysis (5-year trend) → Claude API
7. Generate Excel workbook (5 sheets) → save to R2

## Key URLs & Formats
- Report URL: nuvel.co/analyze/{TICKER}/{TYPE}/{YEAR}
  Example: nuvel.co/analyze/NVDA/10-K/2024
- Excel filename: {TICKER}_{TYPE}_{YEAR}_Nuvel.xlsx
  Example: NVDA_10K_2024_Nuvel.xlsx
