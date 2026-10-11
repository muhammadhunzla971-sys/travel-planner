"""API routes."""
from fastapi import APIRouter, HTTPException

from app.llm.client import check as llm_check
from app.models.request import TripRequest
from app.services.budget import CostLevel, allocate_budget
from app.services.orchestrator import PlanResult, plan_trip
from app.services.single_pass import SinglePassResult, run_single_pass
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


@router.get("/llm/check")
async def llm_health() -> dict:
    """Is the Groq key configured and working? (Never returns the key.)"""
    return await llm_check()


@router.post("/agents/preview", response_model=SinglePassResult)
async def agents_preview(request: TripRequest) -> SinglePassResult:
    """Run every agent once (flight, stay, activities, critic) and show what each proposed.
    The negotiation loop that fixes conflicts comes in Step 5."""
    try:
        return await run_single_pass(request)
    except DestinationNotFound as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/plan", response_model=PlanResult)
async def plan(request: TripRequest) -> PlanResult:
    """The full planner: research, agents propose, critic reviews, agents negotiate until the
    plan fits the budget (max 4 rounds). Returns the plan, the budget breakdown and the
    negotiation timeline."""
    try:
        return await plan_trip(request)
    except DestinationNotFound as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
