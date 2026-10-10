"""The building blocks of a plan: flights, stays, activities, day plans, costs.

Every price carries a `source` so the UI can show what is live vs estimated.
"""
from datetime import date, datetime, time
from enum import Enum
from itertools import pairwise

from pydantic import BaseModel, Field


class DataSource(str, Enum):
    live = "live"            # fetched from a real provider
    estimated = "estimated"  # computed / guessed by us or the LLM
    mock = "mock"            # fallback sample data


class FlightOption(BaseModel):
    id: str
    airline: str
    origin: str
    destination: str
    depart_at: datetime
    arrive_at: datetime
    return_depart_at: datetime | None = None
    return_arrive_at: datetime | None = None
    stops: int = Field(default=0, ge=0)
    duration_minutes: int | None = Field(default=None, ge=0)
    total_price: float = Field(ge=0, description="Price for ALL travelers, round trip")
    currency: str
    booking_url: str | None = None
    source: DataSource = DataSource.estimated


class StayOption(BaseModel):
    id: str
    name: str
    kind: str = "hotel"  # hotel | hostel | apartment
    area: str | None = None
    rating: float | None = Field(default=None, ge=0, le=10)
    price_per_night: float = Field(ge=0)
    nights: int = Field(ge=1)
    total_price: float = Field(ge=0)
    currency: str
    latitude: float | None = None
    longitude: float | None = None
    amenities: list[str] = Field(default_factory=list)
    booking_url: str | None = None
    source: DataSource = DataSource.estimated


class ActivityItem(BaseModel):
    id: str
    name: str
    category: str = "sightseeing"  # sightseeing | food | experience | transport ...
    start_time: time | None = None
    duration_minutes: int = Field(default=60, ge=5)
    cost: float = Field(default=0, ge=0)
    area: str | None = None
    notes: str | None = None
    source: DataSource = DataSource.estimated

    @property
    def end_minutes(self) -> int | None:
        if self.start_time is None:
            return None
        return self.start_time.hour * 60 + self.start_time.minute + self.duration_minutes


class DayPlan(BaseModel):
    day_number: int = Field(ge=1)
    date: date
    items: list[ActivityItem] = Field(default_factory=list)
    # Filled by the orchestrator from flight times (e.g. arrival 23:30 => usable_from 23:30)
    usable_from: time | None = None
    usable_until: time | None = None
    notes: str | None = None

    def cost(self) -> float:
        return round(sum(i.cost for i in self.items), 2)

    def has_overlaps(self) -> bool:
        timed = [i for i in self.items if i.start_time is not None]
        timed.sort(key=lambda i: i.start_time)  # type: ignore[arg-type,return-value]
        for a, b in pairwise(timed):
            a_end = a.end_minutes
            b_start = b.start_time.hour * 60 + b.start_time.minute  # type: ignore[union-attr]
            if a_end is not None and a_end > b_start:
                return True
        return False


class CostLine(BaseModel):
    category: str  # flights | stays | activities | food_transport
    description: str
    amount: float = Field(ge=0)
    source: DataSource = DataSource.estimated
