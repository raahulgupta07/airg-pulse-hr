"""Backfill cv_content_hash for existing candidates by SHA-256 of their stored file."""
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, "/app")
from backend.core.database import get_cursor


def main():
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, pdf_path FROM candidates "
            "WHERE cv_content_hash IS NULL AND status='active' "
            "ORDER BY id"
        )
        rows = cur.fetchall()

    print(f"[backfill] {len(rows)} candidates to hash")
    done = 0
    missing = 0
    errors = 0
    dupes_found = 0

    for cid, path in rows:
        if not path or not os.path.exists(path):
            missing += 1
            continue
        try:
            with open(path, "rb") as fh:
                h = hashlib.sha256(fh.read()).hexdigest()
        except Exception as e:
            print(f"  cv_{cid} hash failed: {e}")
            errors += 1
            continue

        # Check for existing dupes (other rows with this hash already stamped)
        with get_cursor() as cur:
            cur.execute(
                "SELECT id FROM candidates WHERE cv_content_hash=%s AND id != %s AND status='active'",
                (h, cid),
            )
            other = cur.fetchone()
            if other:
                dupes_found += 1
                print(f"  cv_{cid} hash collides with cv_{other[0]} (kept both — manual review)")

            cur.execute(
                "UPDATE candidates SET cv_content_hash=%s WHERE id=%s",
                (h, cid),
            )
        done += 1

    print(f"[backfill] done={done} missing_file={missing} errors={errors} dupe_pairs={dupes_found}")


if __name__ == "__main__":
    main()
