"""TTL cache with Redis backend + in-memory fallback.

Public API:
    cache_get(key) -> Any | None
    cache_set(key, value, ttl_s=60)
    cache_delete(key)
    cache_clear_prefix(prefix)

Backward-compat: the legacy `TTLCache` class and module-level `cache`
instance still work (used by routes/positions.py and routes/analytics.py).
When Redis is reachable at import time, the new functional API routes
through Redis; the in-memory `cache` instance keeps working independently.

Module flags:
    _USE_REDIS: bool — True if redis.from_url + ping succeeded at import
    _redis_last_ok: bool — last ping/op result, for /api/health
"""
import os
import time
import json
import pickle
import base64
import threading
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Legacy in-memory TTL cache (kept for backward-compat with existing callers)
# ---------------------------------------------------------------------------
class TTLCache:
    """Thread-safe in-memory cache with per-key TTL."""

    def __init__(self, default_ttl: int = 60):
        self._cache = {}
        self._lock = threading.Lock()
        self.default_ttl = default_ttl

    def get(self, key: str):
        with self._lock:
            if key in self._cache:
                value, expires_at = self._cache[key]
                if time.time() < expires_at:
                    return value
                else:
                    del self._cache[key]
        return None

    def set(self, key: str, value, ttl: int = None):
        ttl = ttl or self.default_ttl
        with self._lock:
            self._cache[key] = (value, time.time() + ttl)

    def delete(self, key: str):
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()

    def clear_prefix(self, prefix: str) -> int:
        with self._lock:
            keys = [k for k in self._cache if k.startswith(prefix)]
            for k in keys:
                del self._cache[k]
        return len(keys)

    def cleanup(self):
        """Remove expired entries."""
        now = time.time()
        with self._lock:
            expired = [k for k, (v, exp) in self._cache.items() if now >= exp]
            for k in expired:
                del self._cache[k]
        return len(expired)


# Global in-memory instance — preserved for backward-compat
cache = TTLCache(default_ttl=60)

# ---------------------------------------------------------------------------
# Redis bootstrap (graceful fallback to in-memory)
# ---------------------------------------------------------------------------
_USE_REDIS: bool = False
_redis_last_ok: bool = False
_r = None  # redis client

_REDIS_URL = os.getenv("REDIS_URL")
if _REDIS_URL:
    try:
        import redis  # type: ignore
        _r = redis.from_url(_REDIS_URL, socket_timeout=2, socket_connect_timeout=2)
        _r.ping()
        _USE_REDIS = True
        _redis_last_ok = True
        logger.info(f"[cache] Redis connected: {_REDIS_URL}")
    except Exception as e:
        _USE_REDIS = False
        _redis_last_ok = False
        _r = None
        logger.warning(
            f"[cache] Redis unavailable ({e!r}); falling back to in-memory TTL cache"
        )
else:
    logger.info("[cache] REDIS_URL not set; using in-memory TTL cache")


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------
_PKL_PREFIX = "pkl:"


def _serialize(value) -> str:
    """JSON-serialize when possible; else pickle with `pkl:` prefix."""
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        return _PKL_PREFIX + base64.b64encode(blob).decode("ascii")


def _deserialize(raw):
    if raw is None:
        return None
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            # raw pickle bytes (legacy)
            try:
                return pickle.loads(raw)
            except Exception:
                return None
    if isinstance(raw, str) and raw.startswith(_PKL_PREFIX):
        try:
            return pickle.loads(base64.b64decode(raw[len(_PKL_PREFIX):]))
        except Exception as e:
            logger.warning(f"[cache] pickle deserialize failed: {e}")
            return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


# ---------------------------------------------------------------------------
# Public functional API
# ---------------------------------------------------------------------------
def cache_get(key: str):
    """Get a cached value or None."""
    global _redis_last_ok
    if _USE_REDIS and _r is not None:
        try:
            raw = _r.get(key)
            _redis_last_ok = True
            return _deserialize(raw)
        except Exception as e:
            _redis_last_ok = False
            logger.warning(f"[cache] redis get failed ({key}): {e}; falling back to memory")
    return cache.get(key)


def cache_set(key: str, value, ttl_s: int = 60) -> None:
    """Set a cached value with TTL (seconds)."""
    global _redis_last_ok
    if _USE_REDIS and _r is not None:
        try:
            payload = _serialize(value)
            _r.setex(key, max(1, int(ttl_s)), payload)
            _redis_last_ok = True
            return
        except Exception as e:
            _redis_last_ok = False
            logger.warning(f"[cache] redis set failed ({key}): {e}; falling back to memory")
    cache.set(key, value, ttl=ttl_s)


def cache_delete(key: str) -> None:
    """Delete a single cache entry (best-effort across both backends)."""
    global _redis_last_ok
    if _USE_REDIS and _r is not None:
        try:
            _r.delete(key)
            _redis_last_ok = True
        except Exception as e:
            _redis_last_ok = False
            logger.warning(f"[cache] redis delete failed ({key}): {e}")
    cache.delete(key)


def cache_clear_prefix(prefix: str) -> int:
    """Clear all keys starting with `prefix`. Returns count removed (in-memory only; Redis count not tracked precisely)."""
    global _redis_last_ok
    removed = 0
    if _USE_REDIS and _r is not None:
        try:
            # SCAN to avoid blocking on large keyspaces
            for k in _r.scan_iter(match=f"{prefix}*", count=500):
                _r.delete(k)
                removed += 1
            _redis_last_ok = True
        except Exception as e:
            _redis_last_ok = False
            logger.warning(f"[cache] redis clear_prefix failed ({prefix}): {e}")
    removed += cache.clear_prefix(prefix)
    return removed


def redis_status():
    """Return status string for /api/health: True | False | 'unavailable'."""
    if not _USE_REDIS:
        return "unavailable"
    if _r is None:
        return False
    try:
        _r.ping()
        return True
    except Exception:
        return False
