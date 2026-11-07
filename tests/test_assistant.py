from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.assistant import health_data
from app.assistant.graph import Plan, parse_plan, run_assistant
from app.assistant.llm import Llms
from app.assistant.prompts import DISCLAIMER, REFUSAL_MESSAGE, UNAVAILABLE_MESSAGE, UNSAFE_REPLY_FALLBACK
from app.assistant.safety import is_medical_request, is_safe_reply
from app.models import BloodPressureReading, GlucoseReading, ReadingType, User

UTC = timezone.utc
NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
OFFSET = 300

SUMMARY_PLAN = '{"intent":"summary","metric":"glucose","period":"last_7_days","compare_with":null}'


class FakeLlm:
    """Stands in for Groq: returns a fixed reply (or raises) and remembers what it was sent."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return SimpleNamespace(content=self.reply)

    def prompt_text(self) -> str:
        return "\n".join(m.content for m in self.calls[-1])


def make_user(db, name):
    user = User(full_name=name, email=f"{name.lower()}@example.com", hashed_password="x")
    db.add(user)
    db.commit()
    return user


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=UTC)


def add_glucose(db, user, when, value, notes=None):
    db.add(
        GlucoseReading(
            user_id=user.id,
            glucose_value=Decimal(str(value)),
            reading_type=ReadingType.FASTING,
            recorded_at=when,
            notes=notes,
        )
    )
    db.commit()


def add_pressure(db, user, when, systolic, diastolic):
    db.add(
        BloodPressureReading(
            user_id=user.id, systolic=systolic, diastolic=diastolic, recorded_at=when
        )
    )
    db.commit()


def run(db, user, question, planner_reply=SUMMARY_PLAN, answer_reply="Your recorded data: fine.", history=None):
    planner = FakeLlm(planner_reply)
    answer = FakeLlm(answer_reply)
    reply = run_assistant(
        db, user.id, question, OFFSET, history or [], Llms(planner=planner, answer=answer), now=NOW
    )
    return reply, planner, answer


# ---------------------------------------------------------------------------
# Safety rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "Do I have diabetes?",
        "What medicine should I take for this?",
        "Should I increase my insulin dose?",
        "Can you diagnose me?",
        "Am I diabetic?",
        "Which tablet is best for high blood pressure?",
    ],
)
def test_medical_requests_are_caught(question):
    assert is_medical_request(question)


@pytest.mark.parametrize(
    "question",
    [
        "Summarize my glucose readings from the last 7 days.",
        "What is my average blood pressure this month?",
        "Compare my readings from this week with last week.",
        "Show me the highest and lowest recorded glucose readings.",
        "Explain my recorded health trends in simple language.",
    ],
)
def test_data_questions_are_allowed(question):
    assert not is_medical_request(question)


@pytest.mark.parametrize(
    "reply",
    [
        "You have diabetes.",
        "You might be hypertensive based on this.",
        "Take 500 mg of metformin twice a day.",
        "Your readings are dangerous.",
        "Your average is within the normal range.",
        "You should increase your insulin.",
    ],
)
def test_unsafe_replies_are_caught(reply):
    assert not is_safe_reply(reply)


@pytest.mark.parametrize(
    "reply",
    [
        "Your recorded data: 4 fasting glucose readings averaged 115. General information: "
        "a healthcare professional can help you interpret them.",
        "Your recorded data: your systolic average was 125 and your diastolic average was 85.",
    ],
)
def test_safe_replies_pass(reply):
    assert is_safe_reply(reply)


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------


def test_medical_questions_get_a_fixed_refusal_and_no_model_call(db_session):
    user = make_user(db_session, "Alice")

    reply, planner, answer = run(db_session, user, "Do I have diabetes?")

    assert REFUSAL_MESSAGE in reply
    assert DISCLAIMER in reply
    assert planner.calls == [] and answer.calls == []


def test_no_readings_gives_an_insufficient_data_message(db_session):
    user = make_user(db_session, "Alice")

    reply, planner, answer = run(db_session, user, "Summarize my glucose readings.")

    assert "no recorded blood glucose readings for the last 7 days" in reply
    assert DISCLAIMER in reply
    assert len(planner.calls) == 1
    assert answer.calls == []


def test_summary_sends_only_numbers_to_the_model(db_session):
    user = make_user(db_session, "Alice")
    for day, value in [(1, 100), (2, 110), (3, 120), (4, 130)]:
        add_glucose(db_session, user, at(11, day), value, notes="SECRET-NOTE")

    reply, planner, answer = run(
        db_session, user, "Summarize my glucose readings from the last 7 days.",
        answer_reply="Your recorded data: 4 readings were recorded.",
    )
    prompt = answer.prompt_text()

    assert reply.startswith("Your recorded data: 4 readings were recorded.")
    assert reply.endswith(DISCLAIMER)
    assert '"average": 115.0' in prompt
    assert "SECRET-NOTE" not in prompt
    assert "alice@example.com" not in prompt
    assert "Alice" not in prompt


def test_compare_two_weeks(db_session):
    user = make_user(db_session, "Alice")
    add_glucose(db_session, user, at(11, 3), 100)
    add_glucose(db_session, user, at(10, 28), 90)
    plan = '{"intent":"compare","metric":"glucose","period":"this_week","compare_with":"last_week"}'

    reply, _planner, answer = run(db_session, user, "Compare this week with last week.", plan)

    assert '"glucose_average_change": 10.0' in answer.prompt_text()
    assert DISCLAIMER in reply


def test_compare_with_a_missing_period_explains_which_one(db_session):
    user = make_user(db_session, "Alice")
    add_glucose(db_session, user, at(11, 3), 100)  # nothing last week
    plan = '{"intent":"compare","metric":"glucose","period":"this_week","compare_with":"last_week"}'

    reply, _planner, answer = run(db_session, user, "Compare this week with last week.", plan)

    assert "no recorded blood glucose readings for last week (Monday to Sunday)" in reply
    assert answer.calls == []


def test_unusable_planner_output_falls_back_to_a_default_plan(db_session):
    user = make_user(db_session, "Alice")
    add_pressure(db_session, user, at(11, 3), 120, 80)

    reply, _planner, answer = run(
        db_session, user, "How am I doing?", planner_reply="sorry, no JSON here"
    )

    assert '"average_systolic": 120.0' in answer.prompt_text()
    assert DISCLAIMER in reply


def test_plan_parsing_fills_in_comparisons():
    filled = parse_plan('{"intent":"compare","metric":"both","period":"this_week"}')
    assert filled.compare_with == "last_week"

    unmappable = parse_plan('{"intent":"compare","metric":"both","period":"last_7_days"}')
    assert unmappable.intent == "summary" and unmappable.compare_with is None

    assert parse_plan("not json") == Plan()
    assert parse_plan('{"intent":"delete everything"}') == Plan()


def test_unsafe_model_reply_is_replaced(db_session):
    user = make_user(db_session, "Alice")
    add_glucose(db_session, user, at(11, 3), 100)

    reply, _planner, _answer = run(
        db_session, user, "Summarize my glucose.",
        answer_reply="You have diabetes. Take 500 mg of metformin.",
    )

    assert UNSAFE_REPLY_FALLBACK in reply
    assert "metformin" not in reply and "diabetes" not in reply
    assert DISCLAIMER in reply


def test_model_failure_gives_a_friendly_message_without_the_error(db_session):
    user = make_user(db_session, "Alice")
    add_glucose(db_session, user, at(11, 3), 100)

    reply, _planner, _answer = run(
        db_session, user, "Summarize my glucose.",
        answer_reply=RuntimeError("boom fake-key-123"),
    )

    assert UNAVAILABLE_MESSAGE in reply
    assert "boom" not in reply and "fake-key-123" not in reply


def test_another_users_readings_never_reach_the_model(db_session):
    alice = make_user(db_session, "Alice")
    bob = make_user(db_session, "Bob")
    add_glucose(db_session, alice, at(11, 3), 100)
    add_glucose(db_session, bob, at(11, 3), 222)

    _reply, _planner, answer = run(db_session, alice, "Show my highest glucose.")

    prompt = answer.prompt_text()
    assert "100.0" in prompt
    assert "222" not in prompt


def test_general_questions_need_no_readings(db_session):
    user = make_user(db_session, "Alice")
    plan = '{"intent":"general","metric":"both","period":"last_7_days","compare_with":null}'

    reply, _planner, answer = run(
        db_session, user, "What does systolic mean?", plan,
        answer_reply="General information: systolic is the upper blood pressure number.",
    )

    assert "No personal readings are needed" in answer.prompt_text()
    assert reply.startswith("General information:")
    assert DISCLAIMER in reply


def test_earlier_messages_are_passed_without_the_disclaimer(db_session):
    user = make_user(db_session, "Alice")
    add_glucose(db_session, user, at(11, 3), 100)
    history = [
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": f"earlier answer\n\n{DISCLAIMER}"},
    ]

    _reply, planner, answer = run(db_session, user, "And now?", history=history)

    assert "earlier question" in planner.prompt_text()
    assert "earlier answer" in answer.prompt_text()
    assert DISCLAIMER not in answer.prompt_text()


def test_plan_periods_match_the_data_module():
    allowed = set(Plan.model_fields["period"].annotation.__args__)
    assert allowed == set(health_data.PERIODS)