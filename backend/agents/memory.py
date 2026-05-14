"""Agno-compatible memory backed by agent_memory table + pgvector recall.

Provides AgnoMemory with:
- recall(query, tenant_id, k) -> list[{key, value}] via cosine similarity
- write(key, value, tenant_id, embed_text_for=None) UPSERT (+ optional embedding)

Embedding uses backend.core.config.embed_text (4-model cascade, 1536-dim).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from backend.core.database import get_cursor

logger = logging.getLogger(__name__)


def _run_sync(coro):
    """Run an async coroutine from a possibly-sync context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _vec_literal(vec: list[float]) -> str:
    """Format a Python list as a pgvector literal."""
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


class AgnoMemory:
    """Long-term agent memory store with semantic recall."""

    def __init__(self, tenant_id: int = 0):
        self.tenant_id = int(tenant_id or 0)

    # ------------------------------------------------------------------
    # Recall — top-k by cosine similarity to query
    # ------------------------------------------------------------------
    def recall(self, query: str, tenant_id: Optional[int] = None,
               k: int = 5) -> list[dict]:
        """Return top-k {key, value} dicts for tenant by semantic similarity."""
        tid = int(tenant_id if tenant_id is not None else self.tenant_id)
        if not query or not query.strip():
            return self._recent(tid, k)

        try:
            from backend.core.config import embed_text
            vec = _run_sync(embed_text(query))
        except Exception as e:
            logger.warning(f"AgnoMemory.recall embed failed: {e}")
            vec = None

        if not vec:
            return self._recent(tid, k)

        vec_lit = _vec_literal(vec)
        try:
            with get_cursor() as cur:
                cur.execute(
                    """
                    SELECT key, value
                    FROM agent_memory
                    WHERE tenant_id = %s AND embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (tid, vec_lit, int(k)),
                )
                rows = cur.fetchall()
        except Exception as e:
            logger.warning(f"AgnoMemory.recall query failed: {e}")
            return []

        out = []
        for r in rows:
            val = r[1]
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except Exception:
                    pass
            out.append({"key": r[0], "value": val})
        return out

    def _recent(self, tid: int, k: int) -> list[dict]:
        """Fallback: most recently updated rows for tenant."""
        try:
            with get_cursor() as cur:
                cur.execute(
                    """SELECT key, value FROM agent_memory
                       WHERE tenant_id = %s
                       ORDER BY updated_at DESC LIMIT %s""",
                    (tid, int(k)),
                )
                rows = cur.fetchall()
            return [{"key": r[0], "value": r[1]} for r in rows]
        except Exception as e:
            logger.warning(f"AgnoMemory recent fallback failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Write — UPSERT with optional embedding
    # ------------------------------------------------------------------
    def write(self, key: str, value: dict, tenant_id: Optional[int] = None,
              embed_text_for: Optional[str] = None,
              updated_by: Optional[int] = None) -> bool:
        """UPSERT a memory row. If embed_text_for is given, embed + store."""
        tid = int(tenant_id if tenant_id is not None else self.tenant_id)
        if not key:
            return False

        embedding_lit: Optional[str] = None
        if embed_text_for:
            try:
                from backend.core.config import embed_text
                vec = _run_sync(embed_text(embed_text_for))
                if vec:
                    embedding_lit = _vec_literal(vec)
            except Exception as e:
                logger.warning(f"AgnoMemory.write embed failed: {e}")

        try:
            payload = json.dumps(value if isinstance(value, (dict, list)) else {"v": value})
            with get_cursor() as cur:
                if embedding_lit:
                    cur.execute(
                        """
                        INSERT INTO agent_memory (tenant_id, key, value, embedding, updated_at, updated_by)
                        VALUES (%s, %s, %s::jsonb, %s::vector, NOW(), %s)
                        ON CONFLICT (tenant_id, key) DO UPDATE
                        SET value = EXCLUDED.value,
                            embedding = EXCLUDED.embedding,
                            updated_at = NOW(),
                            updated_by = EXCLUDED.updated_by
                        """,
                        (tid, key, payload, embedding_lit, updated_by),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO agent_memory (tenant_id, key, value, updated_at, updated_by)
                        VALUES (%s, %s, %s::jsonb, NOW(), %s)
                        ON CONFLICT (tenant_id, key) DO UPDATE
                        SET value = EXCLUDED.value,
                            updated_at = NOW(),
                            updated_by = EXCLUDED.updated_by
                        """,
                        (tid, key, payload, updated_by),
                    )
            return True
        except Exception as e:
            logger.warning(f"AgnoMemory.write failed: {e}")
            return False
