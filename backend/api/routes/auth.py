"""Authentication routes — register, login, refresh, logout, me."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import (
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
    ROLE_DAILY_LIMITS,
    get_current_user,
)
from backend.api.schemas.auth import (
    LoginRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserProfile,
)
from backend.db.database import get_db
from backend.db.models.user import User

router = APIRouter()

JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))


# ---------------------------------------------------------------------------
# Helpers — use bcrypt directly (passlib 1.7.4 is incompatible with bcrypt 4.x:
# its detect_wrap_bug() hashes a string >72 bytes which bcrypt 4.x now rejects)
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode("utf-8")


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _create_token(user_id: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS)
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------

@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user with a role."""
    # Role-specific required fields
    if request.role == "lawyer" and not request.bar_council_id:
        raise HTTPException(422, detail="bar_council_id is required for role 'lawyer'.")
    if request.role == "police" and not request.police_badge_id:
        raise HTTPException(422, detail="police_badge_id is required for role 'police'.")

    # Check for duplicate email
    existing = await db.execute(select(User).where(User.email == request.email))
    if existing.scalar_one_or_none():
        raise HTTPException(409, detail="Email already registered.")

    user = User(
        full_name=request.full_name,
        email=request.email,
        hashed_password=_hash_password(request.password),
        role=request.role,
        bar_council_id=request.bar_council_id,
        police_badge_id=request.police_badge_id,
        organization=request.organization,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return RegisterResponse(
        user_id=str(user.id),
        email=user.email,
        role=user.role,
        created_at=user.created_at,
        message="Registration successful. Please verify your email.",
    )


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate and receive a JWT access token."""
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if not user or not _verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated. Contact support.",
        )

    token = _create_token(user.id, user.role)
    limit = ROLE_DAILY_LIMITS.get(user.role, 20)

    return TokenResponse(
        access_token=token,
        expires_in=JWT_EXPIRY_HOURS * 3600,
        user=UserProfile(
            user_id=str(user.id),
            full_name=user.full_name,
            email=user.email,
            role=user.role,
            created_at=user.created_at,
            query_count_today=user.query_count_today,
            rate_limit_remaining=max(0, limit - user.query_count_today),
        ),
    )


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------

@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(current_user: User = Depends(get_current_user)):
    """Issue a new JWT for a still-authenticated user (sliding session)."""
    token = _create_token(current_user.id, current_user.role)
    return RefreshResponse(
        access_token=token,
        expires_in=JWT_EXPIRY_HOURS * 3600,
    )


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------

@router.post("/logout", status_code=204)
async def logout(current_user: User = Depends(get_current_user)):
    """Logout — client should discard the token.

    Full server-side token blocklisting requires Redis integration (future).
    For now, logout is client-side only (delete token from storage).
    """
    return None


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserProfile)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get the currently authenticated user's profile."""
    limit = ROLE_DAILY_LIMITS.get(current_user.role, 20)
    return UserProfile(
        user_id=str(current_user.id),
        full_name=current_user.full_name,
        email=current_user.email,
        role=current_user.role,
        created_at=current_user.created_at,
        query_count_today=current_user.query_count_today,
        rate_limit_remaining=max(0, limit - current_user.query_count_today),
    )
