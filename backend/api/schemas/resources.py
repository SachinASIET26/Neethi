"""Pydantic schemas for nearby legal resources endpoints."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class NearbyRequest(BaseModel):
    resource_type: Literal["legal_aid", "court", "lawyer", "police_station", "notary"]
    # Location by GPS
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # OR by city
    city: Optional[str] = None
    state: Optional[str] = None

    radius_km: int = Field(10, ge=1, le=50)
    limit: int = Field(5, ge=1, le=20)


class ResourceResult(BaseModel):
    name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    distance_km: Optional[float] = None
    open_now: Optional[bool] = None
    services: List[str] = []
    rating: Optional[float] = None
    maps_url: Optional[str] = None


class NearbyResponse(BaseModel):
    resource_type: str
    location: Optional[dict] = None
    results: List[ResourceResult]
    total_found: int
    note: Optional[str] = None


class EligibilityResponse(BaseModel):
    eligible: bool
    basis: str
    entitlements: List[str] = []
    contact: Optional[dict] = None
