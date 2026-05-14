"""FAQ Builder agent — runs nightly (every 24h). Pulls last 30d of Copilot
user questions, embeds, greedy-clusters by cosine >= 0.85, picks clusters
with size >= 3, asks LITE_MODEL for a canonical {question, answer}, full-
refresh writes faq_entries.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone

from backend.core.database import get_cursor
from backend.core.config import LITE_MODEL, llm_call, embed_text, is_ai_available
from backend.agents.registry import heartbeat, cycle_done
from backend.agents.registry import is_enabled, get_interval

logger = logging.getLogger(__name__)

INTERVAL_S = 24 * 60 * 60
AGENT_ID = "faq-builder"
SIM_THRESHOLD = 0.85
MIN_CLUSTER_SIZE = 3
MAX_QUESTIONS = 500  # cap embed cost


def _fetch_recent_user_questions(since_days: int = 30, limit: int = MAX_QUESTIONS) -> list[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    with get_cursor() as cur:
        cur.execute(
            """SELECT content FROM chat_messages
               WHERE role = 'user' AND created_at > %s
                 AND length(content) BETWEEN 8 AND 500
               ORDER BY created_at DESC LIMIT %s""",
            (cutoff, limit),
        )
        return [r[0].strip() for r in cur.fetchall() if r and r[0]]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _greedy_cluster(items: list[tuple[str, list[float]]]) -> list[list[str]]:
    """Returns clusters as lists of question strings."""
    clusters: list[dict] = []  # {centroid: emb, members: [str]}
    for q, emb in items:
        placed = False
        for c in clusters:
            if _cosine(emb, c["centroid"]) >= SIM_THRESHOLD:
                c["members"].append(q)
                placed = True
                break
        if not placed:
            clusters.append({"centroid": emb, "members": [q]})
    return [c["members"] for c in clusters]


def _generate_canonical(cluster_members: list[str]) -> tuple[str, str] | None:
    if not is_ai_available():
        return (cluster_members[0], "(answer pending — LLM unavailable)")
    sample = "\n".join(f"- {m}" for m in cluster_members[:10])
    prompt = (
        "These are user questions to an HR Copilot that all ask roughly the same thing. "
        "Produce a SINGLE canonical FAQ entry. Return ONLY valid JSON: "
        "{\"question\": \"...\", \"answer\": \"...\"}. Answer should be 1–3 sentences, "
        "factual and concise.\n\n"
        f"QUESTIONS:\n{sample}\n\nJSON:"
    )
    out = llm_call(prompt, model=LITE_MODEL, temperature=0.3, max_tokens=400) or ""
    out = re.sub(r"^```(?:json)?\s*|\s*```$", "", out.strip(), flags=re.I | re.M).strip()
    try:
        d = json.loads(out)
        q = (d.get("question") or "").strip()
        a = (d.get("answer") or "").strip()
        if q and a:
            return (q, a)
    except Exception:
        pass
    return (cluster_members[0], out[:500] or "(no answer generated)")


def _truncate_and_insert(rows: list[tuple[str, str, int]]):
    with get_cursor() as cur:
        cur.execute("DELETE FROM faq_entries")  # full refresh
        for q, a, sz in rows:
            cur.execute(
                """INSERT INTO faq_entries (question, answer, cluster_size)
                   VALUES (%s, %s, %s)""",
                (q, a, sz),
            )


async def faq_builder_loop():
    logger.info(f"[faq-builder] starting (interval={INTERVAL_S}s)")
    await asyncio.sleep(60)
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
            heartbeat(AGENT_ID, status="running", action="fetching last 30d questions")
            qs = await asyncio.to_thread(_fetch_recent_user_questions)
            if not qs:
                heartbeat(AGENT_ID, status="idle")
                cycle_done(AGENT_ID, events=0)
                await asyncio.sleep(get_interval(AGENT_ID, INTERVAL_S))
                continue

            # Embed all (with simple dedup)
            seen: dict[str, list[float]] = {}
            heartbeat(AGENT_ID, status="running", action=f"embedding {len(qs)} questions")
            for q in qs:
                key = q.lower().strip()
                if key in seen:
                    continue
                try:
                    emb = await embed_text(q)
                    if emb:
                        seen[key] = emb
                except Exception as e:
                    logger.warning(f"[faq-builder] embed fail: {e}")

            items = [(q, seen[q.lower().strip()]) for q in qs if q.lower().strip() in seen]
            heartbeat(AGENT_ID, status="running", action=f"clustering {len(items)}")
            clusters = await asyncio.to_thread(_greedy_cluster, items)
            big = [c for c in clusters if len(c) >= MIN_CLUSTER_SIZE]

            faq_rows: list[tuple[str, str, int]] = []
            for cluster in big:
                heartbeat(AGENT_ID, status="running",
                          action=f"canonicalizing cluster size={len(cluster)}")
                pair = await asyncio.to_thread(_generate_canonical, cluster)
                if pair:
                    faq_rows.append((pair[0], pair[1], len(cluster)))

            await asyncio.to_thread(_truncate_and_insert, faq_rows)
            events = len(faq_rows)
            heartbeat(AGENT_ID, status="idle")
        except Exception as e:
            err = str(e)[:200]
            logger.exception(f"[faq-builder] cycle error: {e}")
        cycle_done(AGENT_ID, events=events, error=err)
        await asyncio.sleep(get_interval(AGENT_ID, INTERVAL_S))
