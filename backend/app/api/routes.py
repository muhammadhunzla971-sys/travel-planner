"""API routes. Step 2: a budget preview so we can test the models/allocator online."""
from fastapi import APIRouter

from app.models.request import TripRequest
from app.services.budget import CostLevel, allocate_budget

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
