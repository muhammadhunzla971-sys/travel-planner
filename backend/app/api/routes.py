"""API routes."""
from fastapi import APIRouter, HTTPException

from app.models.request import TripRequest
from app.services.budget import CostLevel, allocate_budget
from app.services.trip_data import (
    DataUnavailable,
    DestinationNotFound,
    TripData,
    gather_trip_data,
)

router = APIRouter()


@router.post("/budget/preview")
async def budget_preview(request: TripRequest, cost_level: CostLevel = "medium") -> dict:
    """Validate a trip request and show how the budget would be split."""
    allocation = allocate_budget(request, cost_level)
    return {
        "destination": request.destination,
        "nights": request.nights,
        "travelers": request.travelers,
        "budget_per_person": request.budget_per_person,
        "style": request.preferences.style,
        "cost_level": cost_level,
        "allocation": allocation.amounts(),
        "percentages": allocation.percentages(),
        "currency": allocation.currency,
    }


@router.post("/tools/preview", response_model=TripData)
async def tools_preview(request: TripRequest) -> TripData:
    """Run the data layer (geocoding, currency, weather, places, flights, stays)
    for a trip request. Use this to check which data is live vs estimated."""
    try:
        return await gather_trip_data(request)
    except DestinationNotFound as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
