"""Document Ingestor agent — every 5 min picks up pending org_brain_uploads,
parses PDF/DOCX/TXT, chunks at 500 chars w/ 50 overlap, embeds, inserts into
org_brain table.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from backend.core.database import get_cursor
from backend.core.config import embed_text
from backend.agents.registry import heartbeat, cycle_done
from backend.agents.registry import is_enabled, get_interval

logger = logging.getLogger(__name__)

INTERVAL_S = 5 * 60
AGENT_ID = "doc-ingestor"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def _extract_text_any(file_path: str) -> str:
    """PDF / DOCX / TXT extraction."""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(file_path)
    suffix = p.suffix.lower()

    if suffix == ".txt":
        return p.read_text(encoding="utf-8", errors="ignore")

    if suffix == ".pdf":
        # Prefer cv_parser.extract_pdf if importable; fall back to pypdf
        try:
            from backend.core.cv_parser import extract_pdf
            d = extract_pdf(str(p))
            return d.get("text") or d.get("full_text") or ""
        except Exception as e:
            logger.warning(f"[doc-ingestor] cv_parser.extract_pdf fail ({e}); trying pypdf")
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(p))
                return "\n".join((page.extract_text() or "") for page in reader.pages)
            except Exception as e2:
                raise RuntimeError(f"pdf parse failed: {e2}")

    if suffix in (".docx", ".doc"):
        try:
            from backend.core.cv_parser import extract_docx
            d = extract_docx(str(p))
            return d.get("text") or d.get("full_text") or ""
        except Exception:
            try:
                import docx  # python-docx
                doc = docx.Document(str(p))
                return "\n".join(par.text for par in doc.paragraphs)
            except Exception as e:
                raise RuntimeError(f"docx parse failed: {e}")

    raise ValueError(f"unsupported file type: {suffix}")


def _chunk(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    out = []
    i = 0
    n = len(text)
    while i < n:
        out.append(text[i : i + size])
        if i + size >= n:
            break
        i += max(1, size - overlap)
    return out


def _fetch_pending_uploads(limit: int = 5) -> list[tuple[int, str]]:
    with get_cursor() as cur:
        cur.execute(
            """SELECT id, file_path FROM org_brain_uploads
               WHERE status = 'pending'
               ORDER BY uploaded_at LIMIT %s""",
            (limit,),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


def _mark_status(upload_id: int, status: str, chunks: int = 0, err: str | None = None):
    with get_cursor() as cur:
        cur.execute(
            """UPDATE org_brain_uploads
               SET status = %s, chunks_created = %s, error = %s
               WHERE id = %s""",
            (status, chunks, err, upload_id),
        )


def _insert_chunk(source_doc_id: int, chunk_text: str, embedding: list[float] | None):
    with get_cursor() as cur:
        if embedding is None:
            cur.execute(
                """INSERT INTO org_brain (source_doc_id, chunk_text)
                   VALUES (%s, %s)""",
                (source_doc_id, chunk_text),
            )
        else:
            # pgvector accepts list via psycopg adapter or string fallback
            try:
                cur.execute(
                    """INSERT INTO org_brain (source_doc_id, chunk_text, embedding)
                       VALUES (%s, %s, %s)""",
                    (source_doc_id, chunk_text, embedding),
                )
            except Exception:
                vec_str = "[" + ",".join(f"{float(x):.6f}" for x in embedding) + "]"
                cur.execute(
                    """INSERT INTO org_brain (source_doc_id, chunk_text, embedding)
                       VALUES (%s, %s, %s::vector)""",
                    (source_doc_id, chunk_text, vec_str),
                )


async def _process_upload(upload_id: int, file_path: str) -> int:
    text = await asyncio.to_thread(_extract_text_any, file_path)
    chunks = _chunk(text)
    if not chunks:
        return 0
    inserted = 0
    for ch in chunks:
        try:
            emb = await embed_text(ch)
        except Exception as e:
            logger.warning(f"[doc-ingestor] embed failed for upload {upload_id}: {e}")
            emb = None
        await asyncio.to_thread(_insert_chunk, upload_id, ch, emb)
        inserted += 1
    return inserted


async def doc_ingestor_loop():
    logger.info(f"[doc-ingestor] starting (interval={INTERVAL_S}s)")
    await asyncio.sleep(15)
    while True:
        if not is_enabled(AGENT_ID):
            try:
                heartbeat(AGENT_ID, status="disabled", action="off")
            except Exception:
                pass
            await asyncio.sleep(60)
            continue
        events = 0
        err = None
        try:
            heartbeat(AGENT_ID, status="running", action="scanning org_brain_uploads")
            uploads = await asyncio.to_thread(_fetch_pending_uploads)
            for upload_id, fp in uploads:
                heartbeat(AGENT_ID, status="running", action=f"ingesting upload {upload_id}")
                try:
                    n = await _process_upload(upload_id, fp)
                    await asyncio.to_thread(_mark_status, upload_id, "done", n, None)
                    events += 1
                except Exception as ie:
                    msg = str(ie)[:500]
                    logger.warning(f"[doc-ingestor] upload {upload_id} failed: {msg}")
                    await asyncio.to_thread(_mark_status, upload_id, "error", 0, msg)
            heartbeat(AGENT_ID, status="idle")
        except Exception as e:
            err = str(e)[:200]
            logger.exception(f"[doc-ingestor] cycle error: {e}")
        cycle_done(AGENT_ID, events=events, error=err)
        await asyncio.sleep(get_interval(AGENT_ID, INTERVAL_S))
