"""One safe way to call external APIs: timeout + retry with backoff.

Every adapter uses fetch_json so a slow or broken provider never hangs or
crashes the app. After the last retry it raises ProviderError and the adapter
falls back to cached / estimated data.
"""
import asyncio
from typing import Any

import httpx

DEFAULT_TIMEOUT = 8.0
USER_AGENT = ("AITravelPlanner/0.5 (https://travel-planner-amber-nine.vercel.app; "
              "student project; python-httpx)")


class ProviderError(Exception):
    """An external provider failed (network error, bad status, bad JSON)."""


async def fetch_json(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 2,
    backoff: float = 0.4,
    transport: httpx.AsyncBaseTransport | None = None,  # only used in tests
) -> Any:
    last_error: Exception | None = None
    backoff_floor = 0.0
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(
                timeout=timeout, headers={"User-Agent": USER_AGENT}, transport=transport
            ) as client:
                response = await client.get(url, params=params)
            if response.status_code == 429 or response.status_code >= 500:
                if response.status_code == 429:  # honour Retry-After (capped) before the next attempt
                    try:
                        retry_after = min(float(response.headers.get("retry-after", 0)), 5.0)
                    except ValueError:
                        retry_after = 0.0
                    backoff_floor = retry_after
                raise ProviderError(f"{url} returned {response.status_code}")
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError, ProviderError) as exc:
            last_error = exc
            if attempt < retries:
                await asyncio.sleep(max(backoff * (2**attempt), backoff_floor))
    raise ProviderError(f"request failed after {retries + 1} attempts: {last_error}")
