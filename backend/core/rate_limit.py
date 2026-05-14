"""Shared slowapi limiter so route modules can apply per-endpoint limits.

Imported by both backend.main (registers it on app.state) and any route file
that needs `@limiter.limit("...")` on its handlers.
"""
from __future__ import annotations

import os
from slowapi import Limiter
from slowapi.util import get_remote_address

# Global default limit applied via SlowAPIMiddleware. Per-endpoint overrides
# are added via @limiter.limit(...) decorators in route modules.
# Default 600/min = ~10 users × 60 req/min headroom. Bump via RATE_LIMIT env.
_default = os.getenv("RATE_LIMIT", "20000/minute").strip()
# RATE_LIMIT=off / disabled / 0 = use very high cap (slowapi crashes w/ empty list).
# Per-route @limiter.limit(...) still enforce per-endpoint caps (login 5/min, etc).
if _default.lower() in ("off", "disabled", "0", "none", ""):
    _default = "1000000/minute"
limiter = Limiter(key_func=get_remote_address, default_limits=[_default])
