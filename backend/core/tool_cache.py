"""Decorator for caching read-only agent tool results.

Usage:
    @tool_cache(ttl_s=60, key_args=['candidate_id', 'tenant_id'])
    def get_candidate_summary(candidate_id, tenant_id, ...):
        ...

The caller decides which tools are safe to cache (read-only). Mutating
tools must NOT be decorated. Supports both sync and async callables.
"""
import asyncio
import functools
import hashlib
import inspect
import json
import logging
from typing import Iterable, Optional

from backend.core.cache import cache_get, cache_set

logger = logging.getLogger(__name__)


def _build_key(fn_name: str, bound_args: dict, key_args: Optional[Iterable[str]]) -> str:
    if key_args:
        subset = {k: bound_args.get(k) for k in key_args}
    else:
        subset = bound_args
    try:
        payload = json.dumps(subset, sort_keys=True, default=str, ensure_ascii=False)
    except Exception:
        payload = repr(sorted(subset.items()))
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"tool:{fn_name}:{h}"


def tool_cache(ttl_s: int = 60, key_args: Optional[Iterable[str]] = None):
    """Cache a read-only tool's return value.

    Args:
        ttl_s: TTL in seconds (default 60)
        key_args: subset of arg names to include in the cache key.
                  If None, all bound args are used.
    """
    def decorator(fn):
        sig = inspect.signature(fn)
        is_async = asyncio.iscoroutinefunction(fn)
        fn_name = f"{fn.__module__}.{fn.__qualname__}"

        if is_async:
            @functools.wraps(fn)
            async def awrapper(*args, **kwargs):
                try:
                    bound = sig.bind_partial(*args, **kwargs)
                    bound.apply_defaults()
                    key = _build_key(fn_name, dict(bound.arguments), key_args)
                except Exception as e:
                    logger.debug(f"[tool_cache] keygen failed for {fn_name}: {e}")
                    return await fn(*args, **kwargs)

                hit = cache_get(key)
                if hit is not None:
                    return hit
                result = await fn(*args, **kwargs)
                if result is not None:
                    try:
                        cache_set(key, result, ttl_s=ttl_s)
                    except Exception as e:
                        logger.debug(f"[tool_cache] set failed for {fn_name}: {e}")
                return result
            return awrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                bound = sig.bind_partial(*args, **kwargs)
                bound.apply_defaults()
                key = _build_key(fn_name, dict(bound.arguments), key_args)
            except Exception as e:
                logger.debug(f"[tool_cache] keygen failed for {fn_name}: {e}")
                return fn(*args, **kwargs)

            hit = cache_get(key)
            if hit is not None:
                return hit
            result = fn(*args, **kwargs)
            if result is not None:
                try:
                    cache_set(key, result, ttl_s=ttl_s)
                except Exception as e:
                    logger.debug(f"[tool_cache] set failed for {fn_name}: {e}")
            return result
        return wrapper
    return decorator
