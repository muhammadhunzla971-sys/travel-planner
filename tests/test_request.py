from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from tests.conftest import make_request


def test_valid_request_basics():
    r = make_request()
    assert r.currency == "USD"  # normalised
    assert r.nights == 5
    assert r.num_days == 6
    assert r.budget_per_person == 1000.0


def test_start_date_must_be_in_future():
    with pytest.raises(ValidationError):
        make_request(start_date=date.today(), end_date=date.today() + timedelta(days=3))


def test_end_must_be_after_start():
    start = date.today() + timedelta(days=10)
    with pytest.raises(ValidationError):
        make_request(start_date=start, end_date=start)


def test_trip_too_long():
    start = date.today() + timedelta(days=10)
    with pytest.raises(ValidationError):
        make_request(start_date=start, end_date=start + timedelta(days=45))


@pytest.mark.parametrize("budget", [0, -50])
def test_budget_must_be_positive(budget):
    with pytest.raises(ValidationError):
        make_request(budget=budget)


def test_bad_currency_and_travelers():
    with pytest.raises(ValidationError):
        make_request(currency="DOLLARS")
    with pytest.raises(ValidationError):
        make_request(travelers=0)


def test_destination_whitespace_cleaned():
    assert make_request(destination="  New    York ").destination == "New York"
