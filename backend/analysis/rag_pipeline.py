"""
RAG pipeline for SEC 10-K / 10-Q filings.

Handles both real PDFs and EDGAR iXBRL HTML files (the common case).
Embeddings: ChromaDB's built-in ONNX all-MiniLM-L6-v2 (no API key needed).
Answer generation: Claude API (temperature=0, max_tokens=2048).
"""
import logging
import os
import re
from pathlib import Path
from typing import Any

import anthropic
import chromadb
from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

logger = logging.getLogger(__name__)

_CHROMA_DIR = "/tmp/chroma_db"

# ── Section-header patterns ────────────────────────────────────────────────
# Matches "Item 1 ", "Item 1A", "Item 1B", "Item 2"…"Item 8",
# and "Note 1"…"Note 25" (financial statement footnotes).
_SECTION_RE = re.compile(
    r"(?:^|\n)\s*"
    r"(Item\s+1(?:A|B)?|Item\s+[2-9]|Item\s+1[0-5]"
    r"|Note\s+(?:[1-9]|1\d|2[0-5]))"
    r"[\s\.:\-–—]",
    re.IGNORECASE | re.MULTILINE,
)

_SECTION_LABELS = {
    "item 1": "Business",
    "item 1a": "Risk Factors",
    "item 1b": "Unresolved Staff Comments",
    "item 2": "Properties",
    "item 7": "MD&A",
    "item 7a": "Market Risk",
    "item 8": "Financial Statements",
}


# ── Text extraction ────────────────────────────────────────────────────────

def _extract_text_from_html(path: Path) -> list[dict[str, Any]]:
    """Parse iXBRL / HTML EDGAR filing → list of {text, page_number}."""
    from lxml import etree  # noqa: PLC0415

    with path.open("rb") as fh:
        raw = fh.read()

    # lxml's HTML parser handles malformed markup
    root = etree.fromstring(raw, parser=etree.HTMLParser())
    # Remove script/style/ix:hidden noise
    for tag in root.xpath("//script|//style|//*[local-name()='hidden']"):
        tag.getparent().remove(tag)

    full_text = " ".join(root.itertext()).strip()
    # Normalise whitespace
    full_text = re.sub(r"[ \t]{2,}", " ", full_text)
    full_text = re.sub(r"\n{3,}", "\n\n", full_text)

    # HTML filings have no discrete pages; assign synthetic page numbers
    # by splitting into ~3000-char blocks so citations stay meaningful.
    block_size = 3000
    pages = []
    for i in range(0, len(full_text), block_size):
        pages.append({"text": full_text[i : i + block_size], "page_number": i // block_size + 1})
    return pages


def _extract_text_from_pdf(path: Path) -> list[dict[str, Any]]:
    """Extract text from a real PDF, one dict per page."""
    from pypdf import PdfReader  # noqa: PLC0415

    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append({"text": text, "page_number": i})
    return pages


def _extract_pages(pdf_path: str) -> list[dict[str, Any]]:
    path = Path(pdf_path)
    with path.open("rb") as fh:
        header = fh.read(16)
    if header.startswith(b"%PDF"):
        return _extract_text_from_pdf(path)
    return _extract_text_from_html(path)


# ── Section-aware chunking ─────────────────────────────────────────────────

def _detect_section(text: str) -> str:
    """Return the last section header found in text, or 'Preamble'."""
    matches = _SECTION_RE.findall(text)
    if not matches:
        return "Preamble"
    raw = matches[-1].strip().lower()
    return _SECTION_LABELS.get(raw, raw.title())


def _chunk_pages(
    pages: list[dict[str, Any]],
    ticker: str,
    year: str,
    filing_type: str,
    chunk_size: int = 1200,
    overlap: int = 150,
) -> list[dict[str, Any]]:
    """
    Slide a window over every page's text.
    Each chunk carries: {text, section, page_number, ticker, year, filing_type}.
    """
    chunks: list[dict[str, Any]] = []
    current_section = "Preamble"

    for page in pages:
        text = page["text"]
        page_num = page["page_number"]

        # Update running section tracker
        detected = _detect_section(text)
        if detected != "Preamble":
            current_section = detected

        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk_text = text[start:end].strip()
            if chunk_text:
                # Override section if this specific chunk contains a header
                local_section = _detect_section(chunk_text)
                if local_section != "Preamble":
                    current_section = local_section
                chunks.append({
                    "text": chunk_text,
                    "section": current_section,
                    "page_number": page_num,
                    "ticker": ticker.upper(),
                    "year": year,
                    "filing_type": filing_type.upper(),
                })
            start += chunk_size - overlap

    return chunks


# ── Index builder ──────────────────────────────────────────────────────────

def build_index(
    pdf_path: str,
    ticker: str,
    year: str,
    filing_type: str,
) -> chromadb.Collection:
    """
    Parse the filing, chunk it, and persist a ChromaDB collection.
    Collection name: {ticker}_{year}_{filing_type}  e.g. NVDA_2024_10K
    Returns the collection (acts as the retriever).
    """
    collection_name = f"{ticker.upper()}_{year}_{filing_type.upper().replace('-', '')}"
    persist_path = str(Path(_CHROMA_DIR) / collection_name)

    client = chromadb.PersistentClient(path=persist_path)
    ef = ONNXMiniLM_L6_V2()

    # Delete stale collection so re-runs stay idempotent
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass

    collection = client.create_collection(
        name=collection_name,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    logger.info("Extracting text from %s", pdf_path)
    pages = _extract_pages(pdf_path)

    logger.info("Chunking %d pages", len(pages))
    chunks = _chunk_pages(pages, ticker, year, filing_type)
    total = len(chunks)
    logger.info("Total chunks: %d", total)

    batch_size = 100
    for i in range(0, total, batch_size):
        batch = chunks[i : i + batch_size]
        collection.add(
            ids=[f"{collection_name}_{i + j}" for j in range(len(batch))],
            documents=[c["text"] for c in batch],
            metadatas=[
                {
                    "section": c["section"],
                    "page_number": c["page_number"],
                    "ticker": c["ticker"],
                    "year": c["year"],
                    "filing_type": c["filing_type"],
                }
                for c in batch
            ],
        )
        # Progress every 50 chunks (approximate to batch boundaries)
        reported = min(i + batch_size, total)
        if reported % 50 < batch_size:
            print(f"Indexed chunk {reported} of {total}")

    print(f"Indexed chunk {total} of {total}")
    logger.info("Collection '%s' built with %d chunks", collection_name, total)
    return collection


# ── Query with citation ────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a financial analyst assistant. Answer the user's question using ONLY
the provided excerpts from an SEC filing. Be precise and cite your sources.
If the excerpts do not contain enough information, say so explicitly.
Format citations as [Section, Page N]."""


def query_with_citation(
    collection: chromadb.Collection,
    question: str,
    n_results: int = 6,
) -> dict[str, Any]:
    """
    Retrieve the top-n most relevant chunks, then ask Claude to answer
    using only those chunks.

    Returns:
        {
            "answer": str,
            "citations": [{"section": str, "page": int, "excerpt": str}]
        }
    """
    results = collection.query(
        query_texts=[question],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    docs: list[str] = results["documents"][0]
    metas: list[dict] = results["metadatas"][0]

    # Build citations list (deduplicated by section+page)
    seen: set[tuple] = set()
    citations: list[dict[str, Any]] = []
    context_blocks: list[str] = []

    for doc, meta in zip(docs, metas):
        section = meta.get("section", "Unknown")
        page = meta.get("page_number", 0)
        key = (section, page)
        if key not in seen:
            seen.add(key)
            citations.append({"section": section, "page": page, "excerpt": doc[:300]})
        context_blocks.append(
            f"[{section}, Page {page}]\n{doc}"
        )

    context = "\n\n---\n\n".join(context_blocks)
    user_message = f"Excerpts from the filing:\n\n{context}\n\nQuestion: {question}"

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {
            "answer": "ANTHROPIC_API_KEY not set — retrieved context shown in citations only.",
            "citations": citations,
        }

    client = anthropic.Anthropic(api_key=api_key, max_retries=0)
    delay = 15.0
    for attempt in range(1, 7):
        try:
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                temperature=0,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            break
        except (anthropic.RateLimitError, anthropic.APIStatusError) as exc:
            status = getattr(exc, "status_code", 0)
            if status not in (429, 500, 503, 529):
                raise
            logger.warning("Anthropic %s (attempt %d/4): sleeping %.0fs", status or "rate-limit", attempt, delay)
            import time as _time; _time.sleep(delay)
            delay *= 2
    else:
        message = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=2048, temperature=0,
            system=_SYSTEM_PROMPT, messages=[{"role": "user", "content": user_message}],
        )
    answer = message.content[0].text

    return {"answer": answer, "citations": citations}
