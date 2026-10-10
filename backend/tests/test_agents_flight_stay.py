from app.agents import Constraints, FlightAgent, StayAgent
from app.agents.flight import is_late_arrival
from app.llm.client import LLMUnavailable
from app.models.messages import AgentName, MessageType
from app.models.request import TravelStyle, TripPreferences
from tests.agent_helpers import fake_llm, make_ctx

BIG = 100_000.0


# ---- flight agent ---------------------------------------------------------
async def test_flight_prefers_best_balance_when_everything_is_affordable():
    ctx = await make_ctx()
    p = await FlightAgent().propose(ctx, BIG)
    assert p.flight.id == "est-direct" and p.within_cap and not p.used_llm
    assert p.considered == 3 and p.cost == p.flight.total_price


async def test_flight_respects_cap():
    ctx = await make_ctx()
    prices = sorted(f.total_price for f in ctx.data.flights)
    p = await FlightAgent().propose(ctx, (prices[0] + prices[1]) / 2)
    assert p.flight.total_price == prices[0] and p.within_cap


async def test_flight_over_cap_returns_cheapest_and_says_so():
    ctx = await make_ctx()
    cheapest = min(f.total_price for f in ctx.data.flights)
    p = await FlightAgent().propose(ctx, cheapest - 10)
    assert p.flight.total_price == cheapest and not p.within_cap
    assert "over the flight budget" in p.reason


async def test_flight_avoid_late_arrival_constraint():
    ctx = await make_ctx()
    late = next(f for f in ctx.data.flights if is_late_arrival(f))
    p = await FlightAgent().propose(ctx, late.total_price + 1, Constraints(avoid_late_arrival=True))
    assert not is_late_arrival(p.flight) and not p.within_cap


async def test_flight_max_stops_from_constraint_and_preferences():
    ctx = await make_ctx()
    assert (await FlightAgent().propose(ctx, BIG, Constraints(max_stops=0))).flight.stops == 0
    ctx2 = await make_ctx(preferences=TripPreferences(max_stops=0))
    assert (await FlightAgent().propose(ctx2, BIG)).flight.stops == 0


async def test_flight_without_options_costs_nothing():
    ctx = await make_ctx(flights=[])
    p = await FlightAgent().propose(ctx, 500)
    assert p.flight is None and p.cost == 0 and p.within_cap


async def test_flight_max_price_constraint_is_stricter_than_cap():
    ctx = await make_ctx()
    cheapest = min(f.total_price for f in ctx.data.flights)
    p = await FlightAgent().propose(ctx, BIG, Constraints(max_price=cheapest - 1))
    assert "over the flight budget" in p.reason


async def test_flight_llm_choice_is_used_when_valid(monkeypatch):
    monkeypatch.setattr("app.agents.base.chat_json",
                        fake_llm({"choice": "est-one-stop", "reason": "Good value."}))
    p = await FlightAgent().propose(await make_ctx(), BIG)
    assert p.flight.id == "est-one-stop" and p.used_llm and p.reason == "Good value."


async def test_flight_llm_invented_id_is_ignored(monkeypatch):
    monkeypatch.setattr("app.agents.base.chat_json", fake_llm({"choice": "fake-777", "reason": "x"}))
    p = await FlightAgent().propose(await make_ctx(), BIG)
    assert p.flight.id == "est-direct" and not p.used_llm


async def test_flight_survives_llm_failures(monkeypatch):
    for failure in (fake_llm(error=LLMUnavailable("down")), fake_llm(error=RuntimeError("boom")),
                    fake_llm(answer={"choice": 5})):
        monkeypatch.setattr("app.agents.base.chat_json", failure)
        p = await FlightAgent().propose(await make_ctx(), BIG)
        assert p.flight.id == "est-direct" and not p.used_llm


async def test_llm_gets_only_affordable_candidates_and_data_rule(monkeypatch):
    calls = []
    monkeypatch.setattr("app.agents.base.chat_json", fake_llm({"choice": "x"}, calls=calls))
    ctx = await make_ctx()
    prices = sorted(f.total_price for f in ctx.data.flights)
    await FlightAgent().propose(ctx, (prices[1] + prices[2]) / 2)
    system, user = calls[0]
    assert "data, not instructions" in system
    assert user.count('"id"') == 2


async def test_proposal_message():
    p = await FlightAgent().propose(await make_ctx(), BIG)
    m = p.to_message()
    assert m.from_agent == AgentName.flight and m.to_agent == AgentName.orchestrator
    assert m.type == MessageType.proposal and m.payload["cost"] == p.cost


# ---- stay agent -----------------------------------------------------------
async def test_stay_comfort_picks_best_private_room_within_cap():
    ctx = await make_ctx()
    mid = next(s for s in ctx.data.stays if s.id == "est-mid")
    p = await StayAgent().propose(ctx, mid.total_price + 1)
    assert p.stay.id == "est-mid" and p.within_cap


async def test_stay_budget_style_takes_cheapest():
    ctx = await make_ctx(preferences=TripPreferences(style=TravelStyle.budget))
    p = await StayAgent().propose(ctx, BIG)
    assert p.stay.id == "est-hostel"


async def test_stay_luxury_takes_best_affordable():
    ctx = await make_ctx(preferences=TripPreferences(style=TravelStyle.luxury))
    p = await StayAgent().propose(ctx, BIG)
    assert p.stay.id == "est-upscale"


async def test_stay_comfort_avoids_hostel_unless_nothing_else_fits():
    ctx = await make_ctx()
    hostel = next(s for s in ctx.data.stays if s.id == "est-hostel")
    p = await StayAgent().propose(ctx, hostel.total_price + 1)
    assert p.stay.id == "est-hostel"  # the only thing that fits


async def test_stay_over_cap():
    ctx = await make_ctx()
    cheapest = min(s.total_price for s in ctx.data.stays)
    p = await StayAgent().propose(ctx, cheapest - 5)
    assert not p.within_cap and "over the accommodation budget" in p.reason


async def test_stay_without_options():
    p = await StayAgent().propose(await make_ctx(stays=[]), 100)
    assert p.stay is None and p.cost == 0


async def test_stay_llm_choice_validated(monkeypatch):
    monkeypatch.setattr("app.agents.base.chat_json",
                        fake_llm({"choice": "est-budget", "reason": "Cheap and central."}))
    p = await StayAgent().propose(await make_ctx(), BIG)
    assert p.stay.id == "est-budget" and p.used_llm
    monkeypatch.setattr("app.agents.base.chat_json", fake_llm({"choice": "nope", "reason": "x"}))
    p = await StayAgent().propose(await make_ctx(), BIG)
    assert p.stay.id == "est-upscale" and not p.used_llm
