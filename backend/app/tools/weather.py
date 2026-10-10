"""Weather for the trip dates (Open-Meteo, free, no key).

Within ~16 days we use the real forecast. Further out we use the same dates
from last year as a typical-weather guide, labelled "estimated".
"""
from datetime import date, timedelta

from pydantic import BaseModel

from app.models.plan import DataSource
from app.tools.cache import cache, make_key
from app.tools.http import fetch_json

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_DAYS = 15
WEATHER_TTL = 3 * 3600
DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code"


class DayWeather(BaseModel):
    date: date
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    precipitation_mm: float | None = None
    summary: str = "unknown"
    source: DataSource = DataSource.live


def describe_code(code: int | None) -> str:
    if code is None:
        return "unknown"
    if code == 0:
        return "clear sky"
    if code in (1, 2, 3):
        return "partly cloudy"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if code >= 95:
        return "thunderstorm"
    return "mixed"


def one_year_earlier(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # Feb 29
        return d.replace(year=d.year - 1, day=28)


def _parse(data: dict, source: DataSource, shift_to: list[date] | None = None) -> list[DayWeather]:
    daily = data.get("daily") or {}
    times = daily.get("time") or []
    out: list[DayWeather] = []
    for i, t in enumerate(times):
        def pick(key: str, idx: int = i):
            values = daily.get(key) or []
            return values[idx] if idx < len(values) else None

        day = shift_to[i] if shift_to and i < len(shift_to) else date.fromisoformat(t)
        out.append(DayWeather(
            date=day,
            temp_min_c=pick("temperature_2m_min"),
            temp_max_c=pick("temperature_2m_max"),
            precipitation_mm=pick("precipitation_sum"),
            summary=describe_code(pick("weather_code")),
            source=source,
        ))
    return out


async def _get_weather(lat: float, lon: float, start: date, end: date) -> list[DayWeather]:
    if end <= date.today() + timedelta(days=FORECAST_DAYS):
        data = await fetch_json(FORECAST_URL, {
            "latitude": lat, "longitude": lon, "daily": DAILY, "timezone": "auto",
            "start_date": start.isoformat(), "end_date": end.isoformat(),
        })
        return _parse(data, DataSource.live)

    last_start, last_end = one_year_earlier(start), one_year_earlier(end)
    data = await fetch_json(ARCHIVE_URL, {
        "latitude": lat, "longitude": lon, "daily": DAILY, "timezone": "auto",
        "start_date": last_start.isoformat(), "end_date": last_end.isoformat(),
    })
    n_days = (end - start).days + 1
    targets = [start + timedelta(days=i) for i in range(n_days)]
    return _parse(data, DataSource.estimated, shift_to=targets)


async def get_weather(lat: float, lon: float, start: date, end: date) -> list[DayWeather]:
    key = make_key("weather", round(lat, 2), round(lon, 2), start, end)
    result = await cache.get_or_set(key, WEATHER_TTL, lambda: _get_weather(lat, lon, start, end))
    return result or []


def summarize_weather(days: list[DayWeather]) -> str:
    if not days:
        return "Weather data not available."
    temps_max = [d.temp_max_c for d in days if d.temp_max_c is not None]
    temps_min = [d.temp_min_c for d in days if d.temp_min_c is not None]
    rainy = sum(1 for d in days if d.summary in ("rain", "thunderstorm", "snow"))
    parts = []
    if temps_min and temps_max:
        parts.append(f"{min(temps_min):.0f}-{max(temps_max):.0f} C")
    parts.append(f"{rainy} of {len(days)} days with rain/snow")
    note = " (typical weather from last year)" if days[0].source == DataSource.estimated else ""
    return ", ".join(parts) + note

