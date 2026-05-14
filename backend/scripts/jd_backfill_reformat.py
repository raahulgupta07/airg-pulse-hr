"""One-shot: backfill jd_text_raw + reformat low-quality legacy JDs.

Usage (inside container):
  python -m backend.scripts.jd_backfill_reformat            # dry-run report
  python -m backend.scripts.jd_backfill_reformat --apply    # actually reformat
  python -m backend.scripts.jd_backfill_reformat --apply --threshold 0.4
  python -m backend.scripts.jd_backfill_reformat --apply --limit 10
"""
from __future__ import annotations

import argparse
import logging
import time

from backend.core.database import get_cursor
from backend.agents.jd_reformat import safe_reformat, score_structure, REFORMAT_THRESHOLD

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="actually write changes (default = dry-run)")
    p.add_argument("--threshold", type=float, default=REFORMAT_THRESHOLD, help="score below this triggers reformat")
    p.add_argument("--limit", type=int, default=0, help="max JDs to process (0 = all)")
    args = p.parse_args()

    with get_cursor() as cur:
        cur.execute(
            "SELECT id, title, jd_text FROM jd_repository "
            "WHERE jd_text IS NOT NULL AND length(jd_text) > 100 "
            "AND (jd_text_source IS NULL OR jd_text_source IN ('raw', 'extracted')) "
            "ORDER BY id"
        )
        rows = cur.fetchall()

    if args.limit:
        rows = rows[: args.limit]

    print(f"Scanning {len(rows)} JDs (threshold={args.threshold}, apply={args.apply})\n")

    n_skip = n_reformat = n_fail = 0
    for jd_id, title, jd_text in rows:
        score = score_structure(jd_text)
        words = len(jd_text.split())
        if score >= args.threshold:
            print(f"  SKIP   #{jd_id:>4} score={score:.2f} words={words}  {title[:60]}")
            n_skip += 1
            continue

        print(f"  REFMT  #{jd_id:>4} score={score:.2f} words={words}  {title[:60]} ...", end=" ", flush=True)
        if not args.apply:
            print("(dry-run)")
            n_reformat += 1
            continue

        t0 = time.time()
        new_text, source, new_score = safe_reformat(jd_text)
        dt = time.time() - t0

        if source != "ai_reformatted":
            print(f"NO-CHANGE ({dt:.1f}s)")
            n_fail += 1
            continue

        with get_cursor() as cur:
            cur.execute(
                "UPDATE jd_repository SET jd_text=%s, jd_text_raw=COALESCE(jd_text_raw, %s), jd_text_source=%s, reformat_quality_score=%s, updated_at=NOW() WHERE id=%s",
                (new_text, jd_text, source, new_score, jd_id),
            )
        print(f"OK score {score:.2f}→{new_score:.2f} ({dt:.1f}s)")
        n_reformat += 1

    print(f"\nDone. skipped={n_skip} reformatted={n_reformat} failed={n_fail}")


if __name__ == "__main__":
    main()
