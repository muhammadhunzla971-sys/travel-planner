"""API routes."""
import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.llm.client import check as llm_check
from app.models.request import TripRequest
from app.services.budget import CostLevel, allocate_budget
from app.services.orchestrator import PlanResult, TimelineEvent, plan_trip
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


@router.get("/places/debug")
async def places_debug(city: str = "Istanbul") -> dict:
    """Shows what Wikipedia returned for a city and why places were kept or dropped."""
    from app.tools.geo import geocode
    from app.tools.places import diagnose

    dest = await geocode(city)
    if dest is None:
        raise HTTPException(status_code=422, detail=f"Unknown city: {city}")
    return await diagnose(dest)


@router.get("/config")
async def public_config() -> dict:
    """Public settings the website needs (never secrets). Accounts are off unless configured."""
    from app.config import get_settings

    cfg = get_settings()
    return {"supabase_url": cfg.supabase_url or None, "supabase_anon_key": cfg.supabase_anon_key or None}


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


def _sse(event: str, payload: object) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/plan/stream")
async def plan_stream(request: TripRequest) -> StreamingResponse:
    """Same as /plan, but streams progress as Server-Sent Events:
    `step` (one per agent message), then `result` (the full PlanResult) or `error`."""
    queue: asyncio.Queue = asyncio.Queue()

    async def on_event(event: TimelineEvent) -> None:
        await queue.put(("step", event.model_dump(mode="json")))

    async def run() -> None:
        try:
            result = await plan_trip(request, on_event=on_event)
            await queue.put(("result", result.model_dump(mode="json")))
        except DestinationNotFound as exc:
            await queue.put(("error", {"status": 422, "detail": str(exc)}))
        except DataUnavailable as exc:
            await queue.put(("error", {"status": 503, "detail": str(exc)}))
        except Exception:  # noqa: BLE001 - never leave the browser hanging
            await queue.put(("error", {"status": 500, "detail": "Planning failed unexpectedly."}))
        finally:
            await queue.put(("end", None))

    async def stream():
        task = asyncio.create_task(run())
        try:
            yield _sse("start", {"destination": request.destination})
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=10)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if kind == "end":
                    break
                yield _sse(kind, payload)
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform",
                                      "X-Accel-Buffering": "no"})
