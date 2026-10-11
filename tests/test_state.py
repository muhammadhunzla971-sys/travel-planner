from datetime import date, datetime, time, timedelta

from app.models import (
    ActivityItem,
    AgentName,
    DataSource,
    DayPlan,
    FlightOption,
    MessageType,
    StayOption,
    TripState,
    TripStatus,
    make_message,
)
from tests.conftest import make_request


def _flight(price: float) -> FlightOption:
    t = datetime.now() + timedelta(days=30)
    return FlightOption(id="f1", airline="TestAir", origin="LHE", destination="IST",
                        depart_at=t, arrive_at=t + timedelta(hours=7),
                        total_price=price, currency="USD", source=DataSource.mock)


def _stay(total: float) -> StayOption:
    return StayOption(id="s1", name="Hotel Test", price_per_night=total / 5, nights=5,
                      total_price=total, currency="USD")


def test_new_state_defaults():
    s = TripState(request=make_request())
    assert s.status == TripStatus.pending
    assert s.iteration == 0 and s.can_negotiate()
    assert s.total_cost() == 0


def test_message_protocol_and_rounds():
    s = TripState(request=make_request())
    s.next_round()
    m = s.post(make_message(AgentName.orchestrator, AgentName.flight, MessageType.constraint,
                            {"cap_pct": 35}, reason="flight too expensive"))
    assert m.round == 1
    assert s.messages_for("flight")[0].payload["cap_pct"] == 35
    assert s.messages_for("stay") == []


def test_negotiation_round_cap():
    s = TripState(request=make_request(), max_iterations=2)
    s.next_round()
    s.next_round()
    assert not s.can_negotiate()


def test_cost_ledger_and_budget_check():
    s = TripState(request=make_request(budget=2000))
    s.selected_flight = _flight(800)
    s.selected_stay = _stay(700)
    s.days = [DayPlan(day_number=1, date=date.today(),
                      items=[ActivityItem(id="a1", name="Museum", cost=50)])]
    s.food_transport_estimate = 250
    assert s.total_cost() == 1800
    assert s.remaining_budget() == 200
    assert s.is_within_budget()
    s.selected_flight = _flight(1500)
    assert not s.is_within_budget()
    assert {line.category for line in s.cost_ledger()} == {"flights", "stays", "activities", "food_transport"}


def test_every_price_line_has_a_source():
    s = TripState(request=make_request())
    s.selected_flight = _flight(500)
    assert all(line.source for line in s.cost_ledger())


def test_day_overlap_detection():
    ok = DayPlan(day_number=1, date=date.today(), items=[
        ActivityItem(id="a", name="A", start_time=time(9, 0), duration_minutes=60),
        ActivityItem(id="b", name="B", start_time=time(10, 0), duration_minutes=30),
    ])
    bad = DayPlan(day_number=1, date=date.today(), items=[
        ActivityItem(id="a", name="A", start_time=time(9, 0), duration_minutes=90),
        ActivityItem(id="b", name="B", start_time=time(10, 0), duration_minutes=30),
    ])
    assert not ok.has_overlaps()
    assert bad.has_overlaps()
