"""Currency conversion.

Providers tried in order (all free, no key):
  1. open.er-api.com  (160+ currencies, includes PKR, AED, SAR ...)
  2. api.frankfurter.dev (ECB rates, fewer currencies)
  3. rough built-in rates (labelled "estimated", only if both are down)
"""
from pydantic import BaseModel

from app.models.plan import DataSource
from app.tools.cache import cache
from app.tools.http import ProviderError, fetch_json

ER_API_URL = "https://open.er-api.com/v6/latest/USD"
FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
RATES_TTL = 6 * 3600

# Rough USD rates, ONLY used when both live providers fail. Always shown as estimated.
STATIC_USD_RATES: dict[str, float] = {
    "USD": 1.0, "EUR": 0.92, "GBP": 0.79, "PKR": 280.0, "AED": 3.6725, "SAR": 3.75,
    "QAR": 3.64, "TRY": 40.0, "INR": 84.0, "MYR": 4.4, "THB": 35.0, "SGD": 1.34,
    "JPY": 150.0, "CAD": 1.37, "AUD": 1.5, "CNY": 7.2, "EGP": 49.0, "CHF": 0.88,
}


class Rate(BaseModel):
    base: str
    quote: str
    rate: float
    source: DataSource
    provider: str


async def _er_api() -> dict[str, float]:
    data = await fetch_json(ER_API_URL)
    if data.get("result") != "success" or "rates" not in data:
        raise ProviderError("er-api returned an unexpected response")
    return {k.upper(): float(v) for k, v in data["rates"].items()}


async def _frankfurter() -> dict[str, float]:
    data = await fetch_json(FRANKFURTER_URL, {"base": "USD"})
    rates = {k.upper(): float(v) for k, v in data["rates"].items()}
    rates["USD"] = 1.0
    return rates


async def get_usd_rates() -> tuple[dict[str, float], DataSource, str]:
    cached = cache.get("fx|usd")
    if cached is not None:
        return cached
    for provider, fn in (("open.er-api.com", _er_api), ("frankfurter", _frankfurter)):
        try:
            result = (await fn(), DataSource.live, provider)
        except (ProviderError, KeyError, TypeError, ValueError):
            continue
        cache.set("fx|usd", result, RATES_TTL)
        return result
    return dict(STATIC_USD_RATES), DataSource.estimated, "built-in rough rates"


async def get_rate(base: str, quote: str) -> Rate:
    base, quote = base.upper(), quote.upper()
    if base == quote:
        return Rate(base=base, quote=quote, rate=1.0, source=DataSource.live, provider="same currency")
    rates, source, provider = await get_usd_rates()
    if base not in rates or quote not in rates:
        # unknown currency in live data: try the rough table, else give up
        if base in STATIC_USD_RATES and quote in STATIC_USD_RATES:
            rates, source, provider = dict(STATIC_USD_RATES), DataSource.estimated, "built-in rough rates"
        else:
            raise ProviderError(f"no exchange rate available for {base}->{quote}")
    return Rate(base=base, quote=quote, rate=rates[quote] / rates[base], source=source, provider=provider)


async def convert(amount: float, base: str, quote: str) -> tuple[float, Rate]:
    rate = await get_rate(base, quote)
    return round(amount * rate.rate, 2), rate
