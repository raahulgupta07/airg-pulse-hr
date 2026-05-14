"""PostgreSQL-backed job queue. No Redis/Celery needed."""
import json
import logging
import asyncio
from backend.core.database import get_cursor

logger = logging.getLogger(__name__)

def enqueue(job_type: str, payload: dict = None) -> int:
    """Add a job to the queue. Returns job_id."""
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO job_queue (job_type, payload) VALUES (%s, %s) RETURNING id",
            (job_type, json.dumps(payload or {}))
        )
        job_id = cur.fetchone()[0]
    logger.info(f"Job enqueued: {job_type} (id={job_id})")
    return job_id

def get_pending_job():
    """Get next pending job (FIFO). Returns dict or None."""
    with get_cursor() as cur:
        cur.execute("""
            UPDATE job_queue SET status = 'running', started_at = NOW(), attempts = attempts + 1
            WHERE id = (
                SELECT id FROM job_queue
                WHERE status = 'pending' AND attempts < max_attempts
                ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED
            ) RETURNING id, job_type, payload, attempts
        """)
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "job_type": row[1], "payload": row[2], "attempts": row[3]}

def complete_job(job_id: int, result: dict = None):
    with get_cursor() as cur:
        cur.execute(
            "UPDATE job_queue SET status = 'completed', result = %s, completed_at = NOW() WHERE id = %s",
            (json.dumps(result or {}), job_id)
        )

def fail_job(job_id: int, error: str):
    with get_cursor() as cur:
        cur.execute(
            "UPDATE job_queue SET status = 'failed', error = %s WHERE id = %s",
            (error[:500], job_id)
        )

def get_job_status(job_id: int) -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT id, job_type, status, result, error, created_at, completed_at FROM job_queue WHERE id = %s", (job_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [desc[0] for desc in cur.description]
        return dict(zip(cols, row))
