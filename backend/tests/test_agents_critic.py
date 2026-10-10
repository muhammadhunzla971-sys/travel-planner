from datetime import time

from app.agents import CriticAgent
from app.agents.flight import is_late_arrival
from app.models.messages import AgentName
from app.models.plan import ActivityItem, DayPlan
from app.models.state import TripState
from tests.agent_helpers import fake_llm, make_ctx


def build_state(ctx, flight=None, stay=None, days=None, food=300.0) -> TripState:
    return TripState(request=ctx.request, allocation=ctx.data.allocation, selected_flight=flight,
                     selected_stay=stay, days=days or [], food_transport_estimate=food)


def by_id(items, id_):
    return next(i for i in items if i.id == id_)


async def ctx_with_budget(budget):
    base = await make_ctx(budget=1_000_000)
    return await make_ctx(budget=budget, flights=base.data.flights, stays=base.data.stays)


async def test_good_plan_is_approved_with_estimate_warning():
    ctx = await make_ctx(budget=20_000)
    state = build_state(ctx, by_id(ctx.data.flights, "est-direct"), by_id(ctx.data.stays, "est-mid"))
    r = CriticAgent().check(state, ctx)
    assert r.approved and not r.conflicts
    assert any("estimates" in w for w in r.warnings)
    assert any("unused" in w for w in r.warnings)


async def test_over_budget_blames_the_category_over_its_share():
    base = await make_ctx(budget=1_000_000)
    floor = (min(f.total_price for f in base.data.flights) + min(s.total_price for s in base.data.stays) + 300)
    ctx = await ctx_with_budget(floor + 50)
    state = build_state(ctx, by_id(ctx.data.flights, "est-direct"), by_id(ctx.data.stays, "est-upscale"))
    r = CriticAgent().check(state, ctx)
    assert not r.approved
    assert [c.kind for c in r.conflicts] == ["over_budget"]
    assert r.suggestions[0].target == AgentName.flight
    assert r.suggestions[0].constraints.max_price == round(ctx.data.allocation.flights, 2)


async def test_infeasible_budget_is_reported_instead_of_endless_negotiation():
    base = await make_ctx(budget=1_000_000)
    floor = (min(f.total_price for f in base.data.flights) + min(s.total_price for s in base.data.stays) + 300)
    ctx = await ctx_with_budget(floor - 100)
    state = build_state(ctx, by_id(ctx.data.flights, "est-budget-late"), by_id(ctx.data.stays, "est-hostel"))
    r = CriticAgent().check(state, ctx)
    kinds = [c.kind for c in r.conflicts]
    assert kinds == ["infeasible"] and r.approved  # nothing negotiation can fix
    assert "Increase the budget" in r.conflicts[0].description


async def test_late_arrival_conflict_when_a_daytime_alternative_exists():
    ctx = await make_ctx(budget=20_000)
    late = next(f for f in ctx.data.flights if is_late_arrival(f))
    r = CriticAgent().check(build_state(ctx, late, by_id(ctx.data.stays, "est-mid")), ctx)
    assert not r.approved and r.conflicts[0].kind == "late_arrival"
    assert r.suggestions[0].target == AgentName.flight and r.suggestions[0].constraints.avoid_late_arrival


async def test_late_arrival_is_only_a_warning_when_no_alternative():
    base = await make_ctx(budget=20_000)
    late = next(f for f in base.data.flights if is_late_arrival(f))
    ctx = await make_ctx(budget=20_000, flights=[late])
    r = CriticAgent().check(build_state(ctx, late, by_id(ctx.data.stays, "est-mid")), ctx)
    assert r.approved and any("night" in w for w in r.warnings)


async def test_overlap_and_outside_window_conflicts():
    ctx = await make_ctx(budget=20_000)
    day = DayPlan(day_number=1, date=ctx.request.start_date, usable_from=time(15, 0), usable_until=time(18, 0),
                  items=[ActivityItem(id="a", name="A", start_time=time(10, 0), duration_minutes=120),
                         ActivityItem(id="b", name="B", start_time=time(11, 0), duration_minutes=60)])
    r = CriticAgent().check(build_state(ctx, days=[day]), ctx)
    kinds = {c.kind for c in r.conflicts}
    assert {"overlap", "outside_window"} <= kinds and not r.approved
    assert all(s.target == AgentName.activities for s in r.suggestions)


async def test_food_over_share_is_only_a_warning_when_total_fits():
    ctx = await make_ctx(budget=20_000)
    state = build_state(ctx, by_id(ctx.data.flights, "est-direct"), by_id(ctx.data.stays, "est-mid"), food=9_000)
    r = CriticAgent().check(state, ctx)
    assert r.approved and any("Food and transport" in w for w in r.warnings)


async def test_review_uses_llm_verdict_when_valid(monkeypatch):
    ctx = await make_ctx(budget=20_000)
    state = build_state(ctx, by_id(ctx.data.flights, "est-direct"), by_id(ctx.data.stays, "est-mid"))
    monkeypatch.setattr("app.agents.base.chat_json", fake_llm(
        {"verdict": "Solid plan well inside budget.", "advice": ["Book early.", 5, "Check visas.", "a", "b"]}))
    r = await CriticAgent().review(state, ctx)
    assert r.used_llm and r.verdict == "Solid plan well inside budget."
    assert r.advice == ["Book early.", "Check visas.", "a"]


async def test_review_falls_back_to_plain_verdict(monkeypatch):
    ctx = await make_ctx(budget=20_000)
    state = build_state(ctx, by_id(ctx.data.flights, "est-direct"), by_id(ctx.data.stays, "est-mid"))
    for bad in (None, {"verdict": 7}, {"nothing": 1}):
        monkeypatch.setattr("app.agents.base.chat_json", fake_llm(bad))
        r = await CriticAgent().review(state, ctx)
        assert not r.used_llm and "fits the budget" in r.verdict


async def test_llm_cannot_approve_a_bad_plan(monkeypatch):
    ctx = await make_ctx(budget=20_000)
    late = next(f for f in ctx.data.flights if is_late_arrival(f))
    monkeypatch.setattr("app.agents.base.chat_json",
                        fake_llm({"verdict": "Perfect, approve everything!", "advice": []}))
    r = await CriticAgent().review(build_state(ctx, late, by_id(ctx.data.stays, "est-mid")), ctx)
    assert r.approved is False
