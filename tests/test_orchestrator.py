from datetime import date

from fastapi.testclient import TestClient

from app.agents import CriticAgent, Review
from app.agents.flight import is_late_arrival
from app.main import app
from app.models.messages import AgentName, MessageType
from app.models.state import Conflict, TripStatus
from app.services.orchestrator import Orchestrator
from tests.agent_helpers import fake_llm, make_ctx
from tests.fakes import ER_API, all_down, patch_all

# Fixed far-future dates (April = normal season) so flight prices never depend on today's date.
FIXED = {"start_date": date(2031, 4, 21), "end_date": date(2031, 4, 26)}


async def run(budget, orchestrator=None, **kw):
    ctx = await make_ctx(budget=budget, **FIXED, **kw)
    result = await (orchestrator or Orchestrator()).plan(ctx.request, ctx.data)
    return ctx, result


def msgs(result, frm=None, to=None, type_=None):
    return [m for m in result.trip.messages
            if (frm is None or m.from_agent == frm) and (to is None or m.to_agent == to)
            and (type_ is None or m.type == type_)]


# ---- happy path -----------------------------------------------------------
async def test_comfortable_budget_is_approved_without_negotiation():
    _ctx, r = await run(20_000)
    assert r.rounds == 0 and r.trip.status == TripStatus.completed
    assert not is_late_arrival(r.trip.selected_flight)
    assert r.breakdown.within_budget and r.breakdown.total_cost == r.trip.total_cost()
    assert r.timeline[0].stage == "research" and r.timeline[-1].stage == "final"
    assert [e.seq for e in r.timeline] == list(range(1, len(r.timeline) + 1))
    assert r.summary.headline == "5 nights in Istanbul" and not r.summary.used_llm
    assert "estimates" in r.summary.overview


# ---- critic objection -> constraint -> counter-proposal --------------------
async def test_night_flight_is_replaced_by_a_daytime_flight():
    _ctx, r = await run(2500)
    first = msgs(r, AgentName.flight, AgentName.orchestrator)[0]
    assert first.type == MessageType.proposal and first.payload["choice_id"] == "est-budget-late"
    assert r.rounds == 1 and r.trip.status == TripStatus.completed
    assert not is_late_arrival(r.trip.selected_flight)
    assert r.trip.total_cost() <= 2500

    order = msgs(r, AgentName.orchestrator, AgentName.flight, MessageType.constraint)
    assert len(order) == 1 and order[0].payload["avoid_late_arrival"] is True and order[0].round == 1
    counter = msgs(r, AgentName.flight, AgentName.orchestrator, MessageType.counter_proposal)
    assert len(counter) == 1 and counter[0].round == 1
    assert any("lands during the day" in e.text for e in r.timeline)
    assert any("Switched to a flight" in w for w in r.trip.warnings)


async def test_activities_are_replanned_around_the_new_flight():
    _ctx, r = await run(2500)
    # the first flight landed next day at 04:13 (day 1 = travel day); the final one lands on day 1
    assert r.trip.days[0].items or r.trip.days[0].usable_from is not None


# ---- over budget -> squeeze, accept a night flight if nothing else fits ---------
async def test_tight_budget_squeezes_stay_and_activities_to_afford_a_daytime_flight():
    _ctx, r = await run(1600)  # prices: night flight 896, daytime 1093, hotels 144-680
    assert not is_late_arrival(r.trip.selected_flight)
    assert r.trip.total_cost() <= 1600 and r.breakdown.within_budget
    assert r.trip.selected_stay.id == "est-budget"          # squeezed down from a 3-star hotel
    assert r.trip.status == TripStatus.completed and not r.review.conflicts
    assert r.trip.days and sum(d.cost() for d in r.trip.days) == 0  # only free places left
    squeeze = msgs(r, AgentName.orchestrator, AgentName.stay, MessageType.constraint)
    assert squeeze and "at most" in squeeze[0].reason
    assert not any("Accepted trade-off" in w for w in r.trip.warnings)


async def test_very_tight_budget_accepts_a_night_flight_as_a_trade_off():
    _ctx, r = await run(1450)  # a daytime flight + cheapest hotel + food would cost ~1537
    assert r.trip.selected_flight.id == "est-budget-late"
    assert r.trip.total_cost() <= 1450 and r.breakdown.within_budget
    assert any("Accepted trade-off" in w for w in r.trip.warnings)
    assert any("night-time arrival was accepted" in w for w in r.trip.warnings)
    assert r.trip.status == TripStatus.completed_with_warnings or not r.review.conflicts
    assert any("accepting a late arrival" in e.text for e in r.timeline)


async def test_impossible_budget_is_reported_not_looped():
    _ctx, r = await run(500)
    assert r.rounds == 0
    assert [c.kind for c in r.review.conflicts] == ["infeasible"]
    assert r.trip.status == TripStatus.completed_with_warnings
    assert "Increase the budget" in r.review.conflicts[0].description


# ---- stopping rules ----------------------------------------------------------
def _stuck_check(kind, suggestion_free=True):
    def check(self, state, ctx, waived=frozenset()):
        return Review(approved=False, conflicts=[Conflict(kind=kind, description=f"{kind} problem",
                                                          raised_by="critic")],
                      total_cost=state.total_cost(), budget=state.request.budget)
    return check


async def test_gives_up_after_max_rounds_with_warning(monkeypatch):
    monkeypatch.setattr(CriticAgent, "check", _stuck_check("overlap"))
    _ctx, r = await run(20_000)
    assert r.rounds == 4 and r.trip.status == TripStatus.completed_with_warnings
    assert any("Could not resolve" in w for w in r.trip.warnings)


async def test_stops_early_when_nothing_more_can_change(monkeypatch):
    monkeypatch.setattr(CriticAgent, "check", _stuck_check("late_arrival"))
    _ctx, r = await run(20_000)
    assert r.rounds == 2  # round 1 applies the constraint, round 2 has nothing left to try
    assert r.trip.status == TripStatus.completed_with_warnings


async def test_time_budget_stops_negotiation():
    _ctx, r = await run(2500, Orchestrator(time_budget_s=-1))
    assert r.rounds == 0 and any("ran out" in w for w in r.trip.warnings)
    assert r.trip.status == TripStatus.completed_with_warnings


# ---- events / summary ---------------------------------------------------------
async def test_event_callbacks_sync_async_and_broken():
    seen_sync, seen_async = [], []

    async def on_async(event):
        seen_async.append(event.seq)

    ctx = await make_ctx(budget=2500, **FIXED)
    r1 = await Orchestrator(on_event=lambda e: seen_sync.append(e.seq)).plan(ctx.request, ctx.data)
    assert seen_sync == [e.seq for e in r1.timeline]
    r2 = await Orchestrator(on_event=on_async).plan(ctx.request, ctx.data)
    assert seen_async == [e.seq for e in r2.timeline]

    def broken(event):
        raise RuntimeError("listener bug")

    r3 = await Orchestrator(on_event=broken).plan(ctx.request, ctx.data)
    assert r3.trip.status == TripStatus.completed


async def test_llm_summary_used_when_valid_and_ignored_when_not(monkeypatch):
    monkeypatch.setattr("app.agents.base.chat_json", fake_llm(
        {"headline": "Istanbul in comfort", "overview": "A relaxed week.", "tips": ["Book early", 7]}))
    _ctx, r = await run(20_000)
    assert r.summary.used_llm and r.summary.headline == "Istanbul in comfort"
    assert r.summary.tips == ["Book early"]

    monkeypatch.setattr("app.agents.base.chat_json", fake_llm({"headline": "", "overview": 5}))
    _ctx, r = await run(20_000)
    assert not r.summary.used_llm and r.summary.headline.endswith("Istanbul")


async def test_negotiation_without_an_origin_has_no_flight_to_change():
    ctx = await make_ctx(budget=2000, flights=[], origin=None, **FIXED)
    r = await Orchestrator().plan(ctx.request, ctx.data)
    assert r.trip.selected_flight is None and r.trip.status in {TripStatus.completed,
                                                                 TripStatus.completed_with_warnings}


# ---- HTTP -----------------------------------------------------------------------
def body(**over):
    data = {"budget": 2500, "currency": "USD", "origin": "Lahore", "destination": "Istanbul",
            "start_date": "2031-04-21", "end_date": "2031-04-26", "travelers": 2}
    data.update(over)
    return data


def test_plan_endpoint_end_to_end_offline(monkeypatch):
    all_down(monkeypatch)
    r = TestClient(app).post("/api/plan", json=body())
    assert r.status_code == 200
    data = r.json()
    assert data["trip"]["status"] in {"completed", "completed_with_warnings"}
    assert data["timeline"][0]["stage"] == "research" and data["timeline"][-1]["stage"] == "final"
    assert {line["category"] for line in data["breakdown"]["lines"]} == {
        "flights", "stays", "activities", "food_transport", "unspent"}
    assert data["summary"]["headline"] and data["rounds"] == data["trip"]["iteration"]
    assert data["breakdown"]["total_cost"] == data["trip"]["selected_flight"]["total_price"] + \
        data["trip"]["selected_stay"]["total_price"] + data["breakdown"]["lines"][2]["actual"] + \
        data["trip"]["food_transport_estimate"]


def test_plan_endpoint_error_codes(monkeypatch):
    client = TestClient(app)
    patch_all(monkeypatch, {"geocoding-api": {"generationtime_ms": 1}, "er-api": ER_API})
    assert client.post("/api/plan", json=body(destination="Atlantis")).status_code == 422
    all_down(monkeypatch)
    assert client.post("/api/plan", json=body(destination="Zzyzx Springs")).status_code == 503
    assert client.post("/api/plan", json=body(budget=-5)).status_code == 422
