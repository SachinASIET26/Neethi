"""Response cache for Neethi AI — backed by Redis / Upstash.

Wraps every legal query response so identical (or near-identical) queries
served to the same user role skip the LLM pipeline entirely.

Design decisions
────────────────
Cache key
    neethi:v1:{role}:{sha256(normalised_query)[:24]}

    Normalisation: lowercase, strip, collapse whitespace.
    The 24-hex prefix of SHA-256 gives 96 bits of collision resistance —
    astronomically more than needed for a legal-query corpus.

TTL strategy
    DIRECT (Tier 1)  →  86 400 s  (24 h)
        Pure DB lookups.  Statutory text is stable; amendments are rare.
    FULL   (Tier 3)  →   3 600 s  (1 h)
        LLM reasoning over retrieved chunks.  New documents may be indexed
        at any time, so a shorter TTL keeps answers fresh.

Graceful degradation
    Every Redis call is wrapped in try/except.  If the cache is unavailable
    (Upstash down, REDIS_URL missing, connection error) the system continues
    without caching — never raising an exception to the caller.  A warning
    is logged so ops can notice without alarming users.

Redis client
    Uses redis.asyncio (bundled with redis>=4.2.0).
    Works with:
      • Local Redis: REDIS_URL=redis://localhost:6379
      • Upstash TLS:  REDIS_URL=rediss://:<token>@<host>:6380
    The ssl_cert_reqs="none" option is set only when the URL scheme is
    "rediss://" to satisfy Upstash's self-signed cert without disabling
    SSL globally.

Usage
─────
    from backend.services.cache import get_cache

    cache = await get_cache()
    hit = await cache.get(query, user_role)
    if hit:
        return hit
    response = await ... build response ...
    await cache.set(query, user_role, response, tier="direct")
    return response
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory fallback cache (used when Redis is unavailable)
# ---------------------------------------------------------------------------
# Simple dict: key → (response_text, expiry_timestamp)
# Provides process-level caching so repeated queries within the same server
# process skip the LLM even without Redis.

_mem_store: dict[str, tuple[str, float]] = {}


def _mem_get(key: str) -> Optional[str]:
    entry = _mem_store.get(key)
    if entry is None:
        return None
    value, expiry = entry
    if time.monotonic() < expiry:
        return value
    del _mem_store[key]  # expired
    return None


def _mem_set(key: str, value: str, ttl: int) -> None:
    _mem_store[key] = (value, time.monotonic() + ttl)

# ---------------------------------------------------------------------------
# TTLs (seconds)
# ---------------------------------------------------------------------------

TTL_DIRECT = int(os.getenv("CACHE_TTL_DIRECT", "86400"))   # 24 h — DB lookups
TTL_FULL   = int(os.getenv("CACHE_TTL_FULL",   "3600"))    # 1 h  — LLM responses

# Cache key namespace / version — bump the version to instantly invalidate
# all existing cache entries after a schema or data change.
_KEY_PREFIX = "neethi:v1"

# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------

_client: Optional["redis.asyncio.Redis"] = None  # type: ignore[name-defined]
_client_unavailable: bool = False  # set True after first connection failure


async def _get_client() -> Optional["redis.asyncio.Redis"]:  # type: ignore[name-defined]
    """Return a lazily-initialised async Redis client, or None if unavailable."""
    global _client, _client_unavailable

    if _client_unavailable:
        return None
    if _client is not None:
        return _client

    url = os.getenv("REDIS_URL", "")
    if not url:
        logger.warning("cache: REDIS_URL not set — using in-memory cache only")
        _client_unavailable = True
        return None

    try:
        import redis.asyncio as aioredis  # noqa: PLC0415

        kwargs: dict = {}
        if url.startswith("rediss://"):
            # Upstash uses TLS with a self-signed cert; skip peer verification.
            import ssl as _ssl  # noqa: PLC0415
            ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE
            kwargs["ssl"] = ctx

        client = aioredis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,   # fail fast — never block a legal query
            socket_timeout=2,
            **kwargs,
        )
        # Ping to verify the connection is live at startup.
        await client.ping()
        _client = client
        logger.info("cache: Redis connected (%s)", url.split("@")[-1])
        return _client

    except Exception as exc:
        logger.warning("cache: Redis unavailable (%s) — falling back to in-memory cache", exc)
        _client_unavailable = True
        return None


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")


def _normalise(query: str) -> str:
    """Lowercase, strip, collapse whitespace."""
    return _WS_RE.sub(" ", query.lower().strip())


def _make_key(query: str, role: str) -> str:
    """Build a Redis key from a normalised query + user role."""
    digest = hashlib.sha256(_normalise(query).encode()).hexdigest()[:24]
    return f"{_KEY_PREFIX}:{role}:{digest}"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

class ResponseCache:
    """Async wrapper over Redis for caching legal query responses.

    Obtain via ``get_cache()`` (returns the module-level singleton).
    """

    async def get(self, query: str, role: str) -> Optional[str]:
        """Return a cached response string, or None on miss / error.

        Args:
            query: Raw user query.
            role:  User role string (e.g. 'citizen', 'lawyer').

        Returns:
            Cached response string on hit, None otherwise.
        """
        key = _make_key(query, role)
        client = await _get_client()
        if client is None:
            # Redis unavailable — try in-memory fallback
            value = _mem_get(key)
            if value is not None:
                logger.debug("cache: HIT (memory) key=%s", key)
            return value

        try:
            value = await client.get(key)
            if value is not None:
                logger.debug("cache: HIT  key=%s", key)
            else:
                logger.debug("cache: MISS key=%s", key)
            return value
        except Exception as exc:
            logger.warning("cache.get: Redis error (%s) — treating as miss", exc)
            return _mem_get(key)  # fallback to memory on Redis error

    async def set(
        self,
        query: str,
        role: str,
        response: str,
        *,
        tier: str = "full",
    ) -> None:
        """Store a response in the cache with an appropriate TTL.

        Args:
            query:    Raw user query.
            role:     User role string.
            response: Response string to cache.
            tier:     ``'direct'`` or ``'full'`` — controls TTL.
        """
        key = _make_key(query, role)
        ttl = TTL_DIRECT if tier == "direct" else TTL_FULL

        # Always write to in-memory store (fast, no I/O)
        _mem_set(key, response, ttl)

        client = await _get_client()
        if client is None:
            return  # Redis unavailable — memory-only cache is fine

        try:
            await client.setex(key, ttl, response)
            logger.debug("cache: SET  key=%s ttl=%ss", key, ttl)
        except Exception as exc:
            logger.warning("cache.set: Redis error (%s) — response not cached in Redis", exc)

    async def invalidate(self, query: str, role: str) -> bool:
        """Delete a specific cache entry.  Returns True if a key was deleted.

        Useful for admin endpoints that want to force-refresh a specific query.
        """
        client = await _get_client()
        if client is None:
            return False

        key = _make_key(query, role)
        try:
            deleted: int = await client.delete(key)
            if deleted:
                logger.info("cache: INVALIDATED key=%s", key)
            return bool(deleted)
        except Exception as exc:
            logger.warning("cache.invalidate: Redis error (%s)", exc)
            return False

    async def flush_role(self, role: str) -> int:
        """Delete all cache entries for a given role.

        Uses SCAN to avoid blocking the Redis server.  Returns the number
        of keys deleted.

        Warning: O(N) on large caches.  Use sparingly — only for admin
        invalidation after a bulk data ingestion.
        """
        client = await _get_client()
        if client is None:
            return 0

        pattern = f"{_KEY_PREFIX}:{role}:*"
        deleted = 0
        try:
            async for key in client.scan_iter(match=pattern, count=100):
                await client.delete(key)
                deleted += 1
            logger.info("cache: flushed %d keys for role=%s", deleted, role)
            return deleted
        except Exception as exc:
            logger.warning("cache.flush_role: Redis error (%s)", exc)
            return 0

    async def health(self) -> dict:
        """Return a health-check dict suitable for /admin/health responses."""
        client = await _get_client()
        if client is None:
            return {"status": "disabled", "reason": "Redis unavailable or not configured"}
        try:
            pong = await client.ping()
            return {"status": "ok", "ping": pong}
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}


# Module-level singleton — created once and reused across all requests.
_cache_instance: Optional[ResponseCache] = None


async def get_cache() -> ResponseCache:
    """Return the module-level ResponseCache singleton.

    Creates the instance on first call.  The underlying Redis connection is
    established lazily inside ResponseCache.get() / .set().
    """
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = ResponseCache()
    return _cache_instance
