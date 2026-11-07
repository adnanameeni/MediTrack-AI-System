from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.assistant import health_data
from app.models import BloodPressureReading, GlucoseReading, ReadingType, User

UTC = timezone.utc
# Thursday 5 Nov 2026, 09:00 UTC = 14:00 in UTC+05:00
NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
OFFSET = 300


def make_user(db, name):
    user = User(full_name=name, email=f"{name.lower()}@example.com", hashed_password="x")
    db.add(user)
    db.commit()
    return user


def add_glucose(db, user, when, value):
    db.add(
        GlucoseReading(
            user_id=user.id,
            glucose_value=Decimal(str(value)),
            reading_type=ReadingType.FASTING,
            recorded_at=when,
        )
    )
    db.commit()


def add_pressure(db, user, when, systolic, diastolic, pulse=None):
    db.add(
        BloodPressureReading(
            user_id=user.id,
            systolic=systolic,
            diastolic=diastolic,
            pulse=pulse,
            recorded_at=when,
        )
    )
    db.commit()


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------


def test_today_and_last_7_days_use_the_users_time_zone():
    today = health_data.resolve_period("today", OFFSET, NOW)
    assert today.start_utc == datetime(2026, 11, 4, 19, 0, tzinfo=UTC)
    assert today.end_utc == datetime(2026, 11, 5, 19, 0, tzinfo=UTC)
    assert today.first_day == "2026-11-05"
    assert today.last_day == "2026-11-05"

    week = health_data.resolve_period("last_7_days", OFFSET, NOW)
    assert week.start_utc == datetime(2026, 10, 29, 19, 0, tzinfo=UTC)
    assert week.end_utc == datetime(2026, 11, 5, 19, 0, tzinfo=UTC)
    assert week.first_day == "2026-10-30"


def test_weeks_run_monday_to_sunday():
    this_week = health_data.resolve_period("this_week", OFFSET, NOW)
    assert this_week.first_day == "2026-11-02"
    assert this_week.last_day == "2026-11-08"

    last_week = health_data.resolve_period("last_week", OFFSET, NOW)
    assert last_week.first_day == "2026-10-26"
    assert last_week.last_day == "2026-11-01"
    assert last_week.end_utc == this_week.start_utc


def test_months_and_yesterday():
    this_month = health_data.resolve_period("this_month", OFFSET, NOW)
    assert (this_month.first_day, this_month.last_day) == ("2026-11-01", "2026-11-30")

    last_month = health_data.resolve_period("last_month", OFFSET, NOW)
    assert (last_month.first_day, last_month.last_day) == ("2026-10-01", "2026-10-31")

    yesterday = health_data.resolve_period("yesterday", OFFSET, NOW)
    assert yesterday.first_day == "2026-11-04"
    assert yesterday.end_utc == health_data.resolve_period("today", OFFSET, NOW).start_utc


def test_all_time_has_no_first_day():
    assert health_data.resolve_period("all_time", OFFSET, NOW).first_day is None


def test_unknown_period_or_metric_is_rejected(db_session):
    with pytest.raises(ValueError):
        health_data.resolve_period("next_year", OFFSET, NOW)
    with pytest.raises(ValueError):
        health_data.collect_facts(db_session, 1, "weight", "today", OFFSET, NOW)


# ---------------------------------------------------------------------------
# Glucose facts
# ---------------------------------------------------------------------------


def test_glucose_summary_extremes_and_trend(db_session):
    user = make_user(db_session, "Alice")
    for day, value in [(1, 100), (2, 110), (3, 120), (4, 130)]:
        add_glucose(db_session, user, at(11, day), value)

    facts = health_data.collect_facts(db_session, user.id, "glucose", "last_7_days", OFFSET, NOW)
    glucose = facts["glucose"]

    assert health_data.has_data(facts)
    assert glucose["count"] == 4
    assert glucose["average"] == 115.0
    assert glucose["lowest"] == {"value": 100.0, "recorded_at": "2026-11-01 15:00"}
    assert glucose["highest"] == {"value": 130.0, "recorded_at": "2026-11-04 15:00"}
    assert glucose["by_reading_type"]["fasting"] == {"count": 4, "average": 115.0}
    assert glucose["trend"]["earlier_half_average"] == 105.0
    assert glucose["trend"]["later_half_average"] == 125.0
    assert glucose["trend"]["change"] == 20.0
    assert glucose["trend"]["later_compared_with_earlier"] == "higher"
    assert facts["blood_pressure"] is None


def test_no_trend_with_fewer_than_four_readings(db_session):
    user = make_user(db_session, "Alice")
    for day, value in [(1, 100), (2, 110), (3, 120)]:
        add_glucose(db_session, user, at(11, day), value)

    facts = health_data.collect_facts(db_session, user.id, "glucose", "last_7_days", OFFSET, NOW)

    assert facts["glucose"]["count"] == 3
    assert facts["glucose"]["trend"] is None


def test_no_readings_means_no_data(db_session):
    user = make_user(db_session, "Alice")

    facts = health_data.collect_facts(db_session, user.id, "both", "last_7_days", OFFSET, NOW)

    assert facts["glucose"] is None
    assert facts["blood_pressure"] is None
    assert not health_data.has_data(facts)


def test_readings_outside_the_period_are_left_out(db_session):
    user = make_user(db_session, "Alice")
    add_glucose(db_session, user, at(10, 1), 200)  # a month ago
    add_glucose(db_session, user, at(11, 3), 100)

    recent = health_data.collect_facts(db_session, user.id, "glucose", "last_7_days", OFFSET, NOW)
    everything = health_data.collect_facts(db_session, user.id, "glucose", "all_time", OFFSET, NOW)

    assert recent["glucose"]["count"] == 1
    assert everything["glucose"]["count"] == 2
    assert everything["glucose"]["highest"]["value"] == 200.0


# ---------------------------------------------------------------------------
# Blood pressure facts
# ---------------------------------------------------------------------------


def test_blood_pressure_summary_and_flat_trend(db_session):
    user = make_user(db_session, "Alice")
    add_pressure(db_session, user, at(11, 1), 120, 80, 70)
    add_pressure(db_session, user, at(11, 2), 130, 90, None)
    add_pressure(db_session, user, at(11, 3), 110, 70, 60)
    add_pressure(db_session, user, at(11, 4), 140, 100, None)

    facts = health_data.collect_facts(
        db_session, user.id, "blood_pressure", "last_7_days", OFFSET, NOW
    )
    pressure = facts["blood_pressure"]

    assert pressure["count"] == 4
    assert pressure["average_systolic"] == 125.0
    assert pressure["average_diastolic"] == 85.0
    assert pressure["average_pulse"] == 65.0
    assert pressure["highest"]["systolic"] == 140 and pressure["highest"]["diastolic"] == 100
    assert pressure["lowest"]["systolic"] == 110 and pressure["lowest"]["diastolic"] == 70
    assert pressure["trend_systolic"]["later_compared_with_earlier"] == "about the same"
    assert facts["glucose"] is None


def test_average_pulse_is_none_when_no_pulse_was_recorded(db_session):
    user = make_user(db_session, "Alice")
    add_pressure(db_session, user, at(11, 3), 120, 80, None)

    facts = health_data.collect_facts(
        db_session, user.id, "blood_pressure", "last_7_days", OFFSET, NOW
    )

    assert facts["blood_pressure"]["average_pulse"] is None


def test_metric_choice_limits_what_is_returned(db_session):
    user = make_user(db_session, "Alice")
    add_glucose(db_session, user, at(11, 3), 100)
    add_pressure(db_session, user, at(11, 3), 120, 80)

    glucose_only = health_data.collect_facts(db_session, user.id, "glucose", "last_7_days", OFFSET, NOW)
    both = health_data.collect_facts(db_session, user.id, "both", "last_7_days", OFFSET, NOW)

    assert glucose_only["blood_pressure"] is None
    assert both["glucose"] is not None and both["blood_pressure"] is not None


# ---------------------------------------------------------------------------
# User isolation
# ---------------------------------------------------------------------------


def test_one_users_facts_never_include_another_users_readings(db_session):
    alice = make_user(db_session, "Alice")
    bob = make_user(db_session, "Bob")
    add_glucose(db_session, alice, at(11, 3), 100)
    add_glucose(db_session, bob, at(11, 3), 222)
    add_pressure(db_session, bob, at(11, 3), 150, 95)

    alice_facts = health_data.collect_facts(db_session, alice.id, "both", "all_time", OFFSET, NOW)
    bob_facts = health_data.collect_facts(db_session, bob.id, "both", "all_time", OFFSET, NOW)

    assert alice_facts["glucose"]["count"] == 1
    assert alice_facts["glucose"]["highest"]["value"] == 100.0
    assert alice_facts["blood_pressure"] is None
    assert bob_facts["glucose"]["highest"]["value"] == 222.0
    assert bob_facts["blood_pressure"]["count"] == 1


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------


def test_week_over_week_comparison(db_session):
    user = make_user(db_session, "Alice")
    add_glucose(db_session, user, at(11, 3), 100)  # this week
    add_glucose(db_session, user, at(10, 28), 90)  # last week
    add_pressure(db_session, user, at(11, 3), 130, 85)
    add_pressure(db_session, user, at(10, 28), 120, 80)

    current = health_data.collect_facts(db_session, user.id, "both", "this_week", OFFSET, NOW)
    previous = health_data.collect_facts(db_session, user.id, "both", "last_week", OFFSET, NOW)
    comparison = health_data.compare_facts(current, previous)

    assert comparison["current_period"] == "this week (Monday to Sunday)"
    assert comparison["previous_period"] == "last week (Monday to Sunday)"
    assert comparison["glucose_average_change"] == 10.0
    assert comparison["systolic_average_change"] == 10.0
    assert comparison["diastolic_average_change"] == 5.0


def test_comparison_is_none_when_one_period_has_no_data(db_session):
    user = make_user(db_session, "Alice")
    add_glucose(db_session, user, at(11, 3), 100)  # only this week

    current = health_data.collect_facts(db_session, user.id, "glucose", "this_week", OFFSET, NOW)
    previous = health_data.collect_facts(db_session, user.id, "glucose", "last_week", OFFSET, NOW)

    assert health_data.compare_facts(current, previous)["glucose_average_change"] is None