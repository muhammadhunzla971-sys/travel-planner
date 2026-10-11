from app.models.messages import AgentName
from app.models.plan import ActivityItem, DayPlan
from app.models.state import TripState
from app.services.negotiation import FLEXIBILITY, build_breakdown, squeeze_targets
from tests.agent_helpers import make_ctx

A, S, F = AgentName.activities, AgentName.stay, AgentName.flight


def test_flexibility_shares_add_up():
    assert abs(sum(FLEXIBILITY.values()) - 1.0) < 1e-9
    assert FLEXIBILITY[A] > FLEXIBILITY[S] > FLEXIBILITY[F]


def test_squeeze_takes_from_activities_first_and_only_as_much_as_needed():
    costs = {A: 100.0, S: 400.0, F: 1000.0}
    floors = {A: 0.0, S: 100.0, F: 900.0}
    targets, unmet = squeeze_targets(costs, floors, 30.0)
    assert unmet == 0
    assert targets == {A: 70.0, S: 400.0, F: 1000.0}  # hotel and flight untouched


def test_squeeze_shares_the_rest_between_stay_and_flight_when_activities_run_out():
    costs = {A: 100.0, S: 400.0, F: 1000.0}
    floors = {A: 0.0, S: 100.0, F: 900.0}
    targets, unmet = squeeze_targets(costs, floors, 250.0)  # activities 100, then 150 split 35:20
    assert unmet == 0 and targets[A] == 0.0
    assert abs((400 - targets[S]) - 150 * 35 / 55) < 0.02
    assert abs((1000 - targets[F]) - 150 * 20 / 55) < 0.02


def test_squeeze_never_goes_below_floors_and_reports_the_rest():
    costs = {A: 100.0, S: 400.0, F: 1000.0}
    floors = {A: 0.0, S: 100.0, F: 900.0}
    targets, unmet = squeeze_targets(costs, floors, 1000.0)
    assert targets == floors
    assert unmet == 500.0


def test_squeeze_redistributes_when_one_agent_runs_out():
    costs = {A: 10.0, S: 400.0, F: 1000.0}
    floors = {A: 0.0, S: 0.0, F: 1000.0}
    targets, unmet = squeeze_targets(costs, floors, 100.0)
    assert unmet == 0 and targets[A] == 0.0 and targets[F] == 1000.0
    assert round(costs[S] - targets[S] + 10, 1) >= 99.9  # stay covered what activities could not


def test_squeeze_with_nothing_to_cut_and_cent_rounding():
    costs = {A: 50.0, S: 100.0, F: 300.0}
    floors = {A: 0.0, S: 0.0, F: 0.0}
    assert squeeze_targets(costs, floors, 0.0) == (costs, 0.0)
    targets, unmet = squeeze_targets(costs, floors, 33.333)
    assert unmet == 0
    assert sum(costs.values()) - sum(targets.values()) >= 33.333 - 1e-6  # never cuts too little


async def test_breakdown_shows_planned_vs_actual():
    ctx = await make_ctx(budget=5000)
    flight = next(f for f in ctx.data.flights if f.id == "est-direct")
    stay = next(s for s in ctx.data.stays if s.id == "est-mid")
    day = DayPlan(day_number=1, date=ctx.request.start_date,
                  items=[ActivityItem(id="a", name="A", cost=40.0)])
    state = TripState(request=ctx.request, allocation=ctx.data.allocation, selected_flight=flight,
                      selected_stay=stay, days=[day], food_transport_estimate=300.0)
    b = build_breakdown(state)
    lines = {line.category: line for line in b.lines}
    assert lines["flights"].actual == flight.total_price
    assert lines["flights"].delta == round(flight.total_price - ctx.data.allocation.flights, 2)
    assert lines["activities"].actual == 40.0 and lines["food_transport"].actual == 300.0
    assert b.total_cost == round(flight.total_price + stay.total_price + 340.0, 2)
    assert b.remaining == round(5000 - b.total_cost, 2) and b.within_budget
    assert lines["unspent"].actual == b.remaining
