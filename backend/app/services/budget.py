"""Budget allocator: splits the total budget across categories.

Starts from a base split, then adjusts for travel style, trip length and how
expensive the destination is. Also has helpers the orchestrator uses during
negotiation (cap a category, move money between categories).
"""
from typing import Literal

from app.models.allocation import CATEGORIES, BudgetAllocation
from app.models.request import TravelStyle, TripRequest

CostLevel = Literal["low", "medium", "high"]

BASE_SHARES = {
    "flights": 0.35,
    "stays": 0.35,
    "activities": 0.15,
    "food_transport": 0.10,
    "buffer": 0.05,
}

# Each adjustment dict sums to 0, so the total stays 1.0 before normalising.
STYLE_ADJUSTMENTS = {
    TravelStyle.budget: {"stays": -0.05, "food_transport": +0.05},
    TravelStyle.comfort: {},
    TravelStyle.luxury: {"stays": +0.07, "flights": -0.05, "food_transport": -0.02},
}
SHORT_TRIP = {"flights": +0.05, "stays": -0.03, "activities": -0.02}   # <= 3 nights
LONG_TRIP = {"flights": -0.07, "stays": +0.05, "food_transport": +0.02}  # >= 10 nights
COST_LEVEL_ADJUSTMENTS = {
    "low": {"flights": +0.05, "stays": -0.03, "food_transport": -0.02},
    "medium": {},
    "high": {"flights": -0.05, "stays": +0.03, "food_transport": +0.02},
}
MIN_SHARE = 0.03


def _build(total: float, currency: str, shares: dict[str, float]) -> BudgetAllocation:
    amounts = {c: round(total * shares[c], 2) for c in CATEGORIES}
    # put rounding leftovers into the buffer so the sum is exact
    amounts["buffer"] = round(amounts["buffer"] + (total - sum(amounts.values())), 2)
    return BudgetAllocation(currency=currency, total=round(total, 2), **amounts)


def allocate_budget(request: TripRequest, cost_level: CostLevel = "medium") -> BudgetAllocation:
    shares = dict(BASE_SHARES)

    def apply(adj: dict[str, float]) -> None:
        for cat, delta in adj.items():
            shares[cat] += delta

    apply(STYLE_ADJUSTMENTS[request.preferences.style])
    if request.nights <= 3:
        apply(SHORT_TRIP)
    elif request.nights >= 10:
        apply(LONG_TRIP)
    apply(COST_LEVEL_ADJUSTMENTS[cost_level])

    # never let a category collapse, then normalise back to 1.0
    shares = {c: max(s, MIN_SHARE) for c, s in shares.items()}
    norm = sum(shares.values())
    shares = {c: s / norm for c, s in shares.items()}
    return _build(request.budget, request.currency, shares)


def shift_budget(
    alloc: BudgetAllocation, from_cat: str, to_cat: str, amount: float
) -> BudgetAllocation:
    """Move `amount` from one category to another (total stays the same)."""
    if from_cat not in CATEGORIES or to_cat not in CATEGORIES:
        raise ValueError("unknown category")
    if from_cat == to_cat:
        return alloc
    if amount < 0:
        raise ValueError("amount must be >= 0")
    amounts = alloc.amounts()
    if amount > amounts[from_cat]:
        raise ValueError(f"{from_cat} only has {amounts[from_cat]} to give")
    amounts[from_cat] = round(amounts[from_cat] - amount, 2)
    amounts[to_cat] = round(amounts[to_cat] + amount, 2)
    return alloc.model_copy(update=amounts)


def cap_category(alloc: BudgetAllocation, category: str, cap: float) -> BudgetAllocation:
    """Lower a category to `cap` and hand the freed money to the other
    categories (not the buffer), in proportion to their current size.
    This is what the orchestrator does when e.g. flights ask for too much.
    """
    if category not in CATEGORIES or category == "buffer":
        raise ValueError("cannot cap this category")
    current = alloc.amounts()[category]
    if cap < 0:
        raise ValueError("cap must be >= 0")
    if cap >= current:
        return alloc  # already within the cap

    freed = round(current - cap, 2)
    receivers = [c for c in CATEGORIES if c not in (category, "buffer")]
    base = sum(alloc.amounts()[c] for c in receivers)
    amounts = alloc.amounts()
    amounts[category] = round(cap, 2)
    given = 0.0
    for c in receivers:
        part = round(freed * amounts[c] / base, 2)
        amounts[c] = round(amounts[c] + part, 2)
        given = round(given + part, 2)
    amounts["buffer"] = round(amounts["buffer"] + (freed - given), 2)  # rounding leftovers
    return alloc.model_copy(update=amounts)
