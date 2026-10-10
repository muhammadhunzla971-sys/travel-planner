"""How the total budget is split across categories."""
from pydantic import BaseModel, model_validator

CATEGORIES = ("flights", "stays", "activities", "food_transport", "buffer")


class BudgetAllocation(BaseModel):
    currency: str
    total: float
    flights: float
    stays: float
    activities: float
    food_transport: float
    buffer: float

    @model_validator(mode="after")
    def _sums_to_total(self) -> "BudgetAllocation":
        if abs(self.allocated() - self.total) > 0.011:
            raise ValueError("categories must add up to the total budget")
        return self

    def amounts(self) -> dict[str, float]:
        return {c: getattr(self, c) for c in CATEGORIES}

    def allocated(self) -> float:
        return round(sum(self.amounts().values()), 2)

    def percentages(self) -> dict[str, float]:
        return {c: round(v / self.total * 100, 1) for c, v in self.amounts().items()}
