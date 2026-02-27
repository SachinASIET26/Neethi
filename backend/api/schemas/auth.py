"""Pydantic schemas for authentication endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    role: Literal["citizen", "lawyer", "legal_advisor", "police", "admin"]
    bar_council_id: Optional[str] = Field(None, max_length=100)
    police_badge_id: Optional[str] = Field(None, max_length=100)
    organization: Optional[str] = Field(None, max_length=200)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        return v

    @field_validator("bar_council_id")
    @classmethod
    def bar_council_required_for_lawyer(
        cls, v: Optional[str], info
    ) -> Optional[str]:
        # Cross-field validation done at route level (role not available here)
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: "UserProfile"


class UserProfile(BaseModel):
    user_id: str
    full_name: str
    email: str
    role: str
    created_at: datetime
    query_count_today: int = 0
    rate_limit_remaining: int = 0

    model_config = {"from_attributes": True}


class RegisterResponse(BaseModel):
    user_id: str
    email: str
    role: str
    created_at: datetime
    message: str


class RefreshResponse(BaseModel):
    access_token: str
    expires_in: int
