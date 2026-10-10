"""What the customer sends us: budget, destination, dates (+ optional preferences)."""
from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_TRIP_NIGHTS = 30


class TravelStyle(str, Enum):
    budget = "budget"
    comfort = "comfort"
    luxury = "luxury"


class Pace(str, Enum):
    relaxed = "relaxed"
    balanced = "balanced"
    packed = "packed"


class TripPreferences(BaseModel):
    style: TravelStyle = TravelStyle.comfort
    pace: Pace = Pace.balanced
    interests: list[str] = Field(default_factory=list)  # food, history, nature, nightlife, family
    dietary_needs: list[str] = Field(default_factory=list)
    max_stops: int | None = Field(default=None, ge=0, le=3)
    min_hotel_stars: int | None = Field(default=None, ge=1, le=5)


class TripRequest(BaseModel):
    budget: float = Field(gt=0, description="Total budget for the whole trip")
    currency: str = Field(default="USD", description="3-letter code, e.g. USD, PKR, EUR")
    origin: str | None = Field(default=None, max_length=80)
    destination: str = Field(min_length=2, max_length=80)
    start_date: date
    end_date: date
    travelers: int = Field(default=1, ge=1, le=10)
    flexible_days: int = Field(default=0, ge=0, le=7, description="Dates can shift +/- N days")
    preferences: TripPreferences = Field(default_factory=TripPreferences)

    @field_validator("currency")
    @classmethod
    def _currency_code(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 3 or not v.isalpha():
            raise ValueError("currency must be a 3-letter code like USD or PKR")
        return v

    @field_validator("destination", "origin")
    @classmethod
    def _clean_text(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = " ".join(v.split())  # trim + collapse whitespace
        return v or None

    @model_validator(mode="after")
    def _check_dates(self) -> "TripRequest":
        if self.start_date <= date.today():
            raise ValueError("start_date must be in the future")
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if self.nights > MAX_TRIP_NIGHTS:
            raise ValueError(f"trip is too long (max {MAX_TRIP_NIGHTS} nights)")
        return self

    @property
    def nights(self) -> int:
        return (self.end_date - self.start_date).days

    @property
    def num_days(self) -> int:
        return self.nights + 1

    @property
    def budget_per_person(self) -> float:
        return round(self.budget / self.travelers, 2)
