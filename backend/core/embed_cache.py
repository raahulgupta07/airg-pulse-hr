"""Semantic-key cache for query embeddings.

Wraps `embed_text` from backend.core.config. Key = embed:{model}:{sha256(text)}.
24h TTL. When Redis is unavailable AND text > 10000 chars, skip caching to
avoid blowing in-memory RAM.
"""
import hashlib
import logging
from typing import Optional

from backend.core import cache as _cache_mod
from backend.core.cache import cache_get, cache_set
from backend.core.config import embed_text, EMBEDDING_MODELS

logger = logging.getLogger(__name__)

_TTL_S = 24 * 60 * 60   # 24h
_MAX_INMEM_TEXT = 10_000


def _key(text: str, model: str) -> str:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"embed:{model}:{h}"


async def cached_embed(text: str, model: Optional[str] = None) -> Optional[list]:
    """Embed text with 24h cache. Returns vector or None on failure.

    `model` is used purely as the cache namespace; the underlying
    `embed_text` cascades through EMBEDDING_MODELS internally.
    """
    if not text:
        return None

    model = model or (EMBEDDING_MODELS[0] if EMBEDDING_MODELS else "default")

    # Skip cache for very large text when only in-memory backend is available
    skip_cache = (not _cache_mod._USE_REDIS) and (len(text) > _MAX_INMEM_TEXT)

    key = _key(text, model)
    if not skip_cache:
        hit = cache_get(key)
        if hit is not None:
            return hit

    vec = await embed_text(text)
    if vec is not None and not skip_cache:
        try:
            cache_set(key, vec, ttl_s=_TTL_S)
        except Exception as e:
            logger.warning(f"[embed_cache] set failed: {e}")
    return vec
