"""FastAPI shared dependencies — JWT auth, role checking, DB session, cache."""

from __future__ import annotations

import os
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.db.models.user import User
from backend.services.cache import ResponseCache

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production-very-long-secret")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

ROLE_DAILY_LIMITS = {
    "citizen":      20,
    "lawyer":      100,
    "legal_advisor": 100,
    "police":       50,
    "admin":      99999,
}

security = HTTPBearer(auto_error=True)

# ---------------------------------------------------------------------------
# Cache singleton (attached to app.state at startup)
# ---------------------------------------------------------------------------

_cache_instance: ResponseCache | None = None


def get_cache() -> ResponseCache:
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = ResponseCache()
    return _cache_instance


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises 401 on any failure."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is invalid or has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ---------------------------------------------------------------------------
# Current-user dependency
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate JWT and return the authenticated User ORM object."""
    payload = decode_token(credentials.credentials)
    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload missing subject.",
        )

    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated.",
        )
    return user


# ---------------------------------------------------------------------------
# Role-based access dependency factory
# ---------------------------------------------------------------------------

def require_role(*allowed_roles: str) -> Callable:
    """Return a FastAPI dependency that enforces role membership.

    Usage::

        @router.post("/cases/analyze")
        async def analyze(user = Depends(require_role("lawyer", "legal_advisor"))):
            ...
    """
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This endpoint requires one of: {', '.join(allowed_roles)}. "
                    f"Your role: {user.role}"
                ),
            )
        return user

    return _check


# ---------------------------------------------------------------------------
# Rate-limit helper (call inside routes)
# ---------------------------------------------------------------------------

async def check_rate_limit(user: User, db: AsyncSession) -> int:
    """Check and increment the user's daily query counter.

    Returns the number of remaining queries after this one.
    Raises 429 if the daily limit is exceeded.
    """
    from datetime import date, datetime, timezone

    limit = ROLE_DAILY_LIMITS.get(user.role, 20)

    # Reset counter if last reset was a different calendar day (UTC)
    today = date.today()
    if user.query_count_reset_at is None or user.query_count_reset_at.date() < today:
        user.query_count_today = 0
        user.query_count_reset_at = datetime.now(timezone.utc)

    if user.query_count_today >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. You have used {user.query_count_today}/{limit} queries today.",
            headers={
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
            },
        )

    user.query_count_today += 1
    await db.commit()
    return limit - user.query_count_today
