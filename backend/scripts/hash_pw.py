"""CLI: bcrypt-hash a password (cost 12) for SUPERADMIN_PASS_HASH seeding.

Usage:
    python -m backend.scripts.hash_pw <password>
"""
from __future__ import annotations

import sys
import bcrypt


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m backend.scripts.hash_pw <password>", file=sys.stderr)
        return 2
    pw = sys.argv[1].encode()
    print(bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
