"""Rough price levels per country, used to ESTIMATE hotel and daily costs when no
live price provider is connected. Everything built from this is labelled "estimated".

multiplier 1.0 = typical mid-priced destination.
"""
from app.models.request import TravelStyle

COUNTRY_PRICE_MULTIPLIER: dict[str, float] = {
    "PK": 0.45, "IN": 0.50, "LK": 0.55, "NP": 0.45, "BD": 0.50, "TH": 0.70, "MY": 0.70,
    "ID": 0.60, "VN": 0.55, "TR": 0.80, "EG": 0.55, "AZ": 0.70, "UZ": 0.55,
    "AE": 1.40, "QA": 1.40, "SA": 1.10, "GB": 1.50, "FR": 1.40, "DE": 1.25, "IT": 1.30,
    "ES": 1.10, "NL": 1.45, "US": 1.60, "CA": 1.30, "AU": 1.50, "JP": 1.20, "SG": 1.60,
    "MV": 1.80, "CH": 2.00,
}
DEFAULT_MULTIPLIER = 1.0

# Typical nightly price in USD for ONE room (hostel: ONE bed) at multiplier 1.0
HOTEL_TIERS: list[dict] = [
    {"key": "hostel", "label": "Hostel", "kind": "hostel", "stars": 1, "base_usd": 18,
     "amenities": ["shared facilities", "wifi"]},
    {"key": "budget", "label": "Budget hotel", "kind": "hotel", "stars": 2, "base_usd": 40,
     "amenities": ["private room", "wifi"]},
    {"key": "mid", "label": "3-star hotel", "kind": "hotel", "stars": 3, "base_usd": 85,
     "amenities": ["private room", "wifi", "breakfast"]},
    {"key": "upscale", "label": "4-star hotel", "kind": "hotel", "stars": 4, "base_usd": 170,
     "amenities": ["private room", "wifi", "breakfast", "gym"]},
]

FOOD_TRANSPORT_USD_PER_PERSON_DAY = 35.0
STYLE_FOOD_FACTOR = {TravelStyle.budget: 0.7, TravelStyle.comfort: 1.0, TravelStyle.luxury: 1.6}


def price_multiplier(country_code: str | None) -> float:
    if not country_code:
        return DEFAULT_MULTIPLIER
    return COUNTRY_PRICE_MULTIPLIER.get(country_code.upper(), DEFAULT_MULTIPLIER)


def cost_level(country_code: str | None) -> str:
    m = price_multiplier(country_code)
    if m < 0.75:
        return "low"
    if m > 1.25:
        return "high"
    return "medium"


def food_transport_usd_per_day(country_code: str | None, style: TravelStyle) -> float:
    return round(FOOD_TRANSPORT_USD_PER_PERSON_DAY * price_multiplier(country_code)
                 * STYLE_FOOD_FACTOR[style], 2)
