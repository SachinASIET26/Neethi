"""Nearby legal resources routes — SERP API powered location search."""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.dependencies import get_current_user
from backend.api.schemas.resources import (
    EligibilityResponse,
    NearbyRequest,
    NearbyResponse,
    ResourceResult,
)
from backend.db.models.user import User

router = APIRouter()

SERP_API_KEY = os.getenv("SERP_API_KEY", "")

# Legal aid income thresholds per state (INR per annum)
_LEGAL_AID_THRESHOLD = 300_000  # ₹3 lakh default (NALSA national threshold)

_RESOURCE_QUERIES = {
    "legal_aid": "District Legal Services Authority DLSA",
    "court":     "district court sessions court",
    "lawyer":    "advocate lawyer near",
    "police_station": "police station thana",
    "notary":    "registered notary public",
}

_RESOURCE_NOTES = {
    "legal_aid": (
        "Free legal aid is available to citizens with annual income below ₹3 lakh "
        "under the Legal Services Authorities Act, 1987. Call NALSA helpline: 15100."
    ),
    "police_station": (
        "You can file an FIR at any police station. "
        "Under BNSS Section 173, the officer in charge must register the FIR and provide a copy free of charge."
    ),
}


# ---------------------------------------------------------------------------
# POST /resources/nearby
# ---------------------------------------------------------------------------

@router.post("/nearby", response_model=NearbyResponse)
async def find_nearby(
    request: NearbyRequest,
    _: User = Depends(get_current_user),
):
    """Find nearby legal resources via SERP API geolocation search."""
    if not SERP_API_KEY:
        # Return mock data when SERP API is not configured
        return _mock_response(request)

    # Build location string
    if request.latitude and request.longitude:
        location_str = f"{request.latitude},{request.longitude}"
    elif request.city:
        location_str = f"{request.city}, {request.state or 'India'}"
    else:
        raise HTTPException(422, detail="Provide either (latitude+longitude) or (city).")

    search_query = (
        f"{_RESOURCE_QUERIES.get(request.resource_type, request.resource_type)} "
        f"near {location_str}"
    )

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://serpapi.com/search",
                params={
                    "engine": "google_maps",
                    "q": search_query,
                    "ll": f"@{location_str},15z" if "," in location_str and request.latitude else None,
                    "type": "search",
                    "num": request.limit,
                    "api_key": SERP_API_KEY,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, detail=f"SERP API error: {exc}") from exc
    except Exception as exc:
        raise HTTPException(502, detail=f"Resource search unavailable: {exc}") from exc

    results: list[ResourceResult] = []
    for place in data.get("local_results", [])[: request.limit]:
        results.append(
            ResourceResult(
                name=place.get("title", ""),
                address=place.get("address"),
                phone=place.get("phone"),
                website=place.get("website"),
                distance_km=_parse_distance(place.get("distance", "")),
                open_now=place.get("open_state") == "Open",
                rating=place.get("rating"),
                maps_url=place.get("links", {}).get("directions"),
            )
        )

    loc_dict = None
    if request.latitude:
        loc_dict = {"latitude": request.latitude, "longitude": request.longitude}

    return NearbyResponse(
        resource_type=request.resource_type,
        location=loc_dict,
        results=results,
        total_found=len(results),
        note=_RESOURCE_NOTES.get(request.resource_type),
    )


def _parse_distance(dist_str: str) -> float | None:
    """Parse '2.3 km' or '500 m' into km float."""
    if not dist_str:
        return None
    try:
        parts = dist_str.lower().split()
        if len(parts) >= 2:
            val = float(parts[0])
            if "m" in parts[1] and "km" not in parts[1]:
                return round(val / 1000, 2)
            return round(val, 2)
    except ValueError:
        return None
    return None


def _mock_response(request: NearbyRequest) -> NearbyResponse:
    """Return a structured placeholder when SERP_API_KEY is not set."""
    return NearbyResponse(
        resource_type=request.resource_type,
        location={"latitude": request.latitude, "longitude": request.longitude} if request.latitude else None,
        results=[
            ResourceResult(
                name="SERP API not configured — configure SERP_API_KEY in .env",
                address="See https://serpapi.com for API key",
                services=["Real results available after SERP_API_KEY is set"],
            )
        ],
        total_found=0,
        note=(
            "This is a placeholder. Set SERP_API_KEY in your .env file to enable "
            "real location-based legal resource search."
        ),
    )


# ---------------------------------------------------------------------------
# GET /resources/legal-aid/eligibility
# ---------------------------------------------------------------------------

@router.get("/legal-aid/eligibility", response_model=EligibilityResponse)
async def check_eligibility(
    annual_income: int = Query(..., ge=0, description="Annual family income in INR"),
    category: str = Query("general", description="sc|st|woman|child|disabled|general"),
    state: str = Query("all", description="State code, e.g. MH, DL, TN"),
    _: User = Depends(get_current_user),
):
    """Check eligibility for free legal aid under Legal Services Authorities Act, 1987."""
    # Special categories are always eligible regardless of income
    always_eligible_categories = {"sc", "st", "woman", "child", "disabled"}
    always_eligible = category.lower() in always_eligible_categories

    # Income-based eligibility
    income_eligible = annual_income <= _LEGAL_AID_THRESHOLD

    eligible = always_eligible or income_eligible

    if always_eligible:
        basis = (
            f"Eligible by category: '{category}' — "
            "SC/ST, women, children, and persons with disabilities are entitled to "
            "free legal aid under Section 12 of the Legal Services Authorities Act, 1987, "
            "regardless of income."
        )
    elif income_eligible:
        basis = (
            f"Annual income ₹{annual_income:,} is below the ₹{_LEGAL_AID_THRESHOLD:,} threshold. "
            "Eligible under Section 12(h) of the Legal Services Authorities Act, 1987."
        )
    else:
        basis = (
            f"Annual income ₹{annual_income:,} exceeds the ₹{_LEGAL_AID_THRESHOLD:,} threshold "
            "and category '{category}' does not qualify for automatic eligibility. "
            "You may still approach DLSA for fee waiver in special circumstances."
        )

    entitlements = (
        [
            "Free legal representation in all courts and tribunals",
            "Court fee waiver",
            "Free copy of court documents",
            "Access to Lok Adalat for pre-litigation settlement",
            "Free legal advice from DLSA panel lawyers",
        ]
        if eligible
        else []
    )

    return EligibilityResponse(
        eligible=eligible,
        basis=basis,
        entitlements=entitlements,
        contact={
            "authority": "District Legal Services Authority (DLSA)",
            "national_helpline": "15100",
            "website": "https://nalsa.gov.in",
            "note": "Visit your nearest DLSA office with income proof and ID.",
        }
        if eligible
        else None,
    )
