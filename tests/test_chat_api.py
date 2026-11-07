from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.assistant import llm as llm_module
from app.assistant.llm import Llms
from app.assistant.prompts import DISCLAIMER
from app.assistant.settings import GroqSettings
from app.dependencies import get_current_user
from app.models import ChatMessage, GlucoseReading, ReadingType, User
from app.routes.chat import get_llms
from main import app

ALL_TIME_PLAN = '{"intent":"summary","metric":"glucose","period":"all_time","compare_with":null}'


class FakeLlm:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content=self.reply)

    def prompt_text(self) -> str:
        return "\n".join(m.content for m in self.calls[-1])


def make_user(db, name):
    user = User(full_name=name, email=f"{name.lower()}@example.com", hashed_password="x")
    db.add(user)
    db.commit()
    return user


def add_reading(db, user, value="100.00"):
    db.add(
        GlucoseReading(
            user_id=user.id,
            glucose_value=Decimal(value),
            reading_type=ReadingType.FASTING,
            recorded_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    db.commit()


@pytest.fixture
def fake_llms():
    llms = Llms(
        planner=FakeLlm(ALL_TIME_PLAN),
        answer=FakeLlm("Your recorded data: one reading was recorded."),
    )
    app.dependency_overrides[get_llms] = lambda: llms
    return llms


@pytest.fixture
def acting(client, db_session):
    """Call acting(user) to choose who is logged in for the next requests."""
    state = {"user": None}
    app.dependency_overrides[get_current_user] = lambda: state["user"]

    def switch(user):
        state["user"] = user

    return switch


def send(client, message="Summarize my glucose", conversation_id=None, **extra):
    body = {"message": message, "offset_minutes": 300, **extra}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    return client.post("/chat/messages", json=body)


def test_chat_requires_login(client):
    assert send(client).status_code in (401, 403)
    assert client.get("/chat/conversations").status_code in (401, 403)


def test_sending_a_message_creates_and_stores_a_conversation(client, db_session, acting, fake_llms):
    alice = make_user(db_session, "Alice")
    add_reading(db_session, alice)
    acting(alice)

    response = send(client)

    assert response.status_code == 200
    body = response.json()
    assert body["user_message"]["role"] == "user"
    assert body["assistant_message"]["role"] == "assistant"
    assert body["assistant_message"]["content"].endswith(DISCLAIMER)

    conversations = client.get("/chat/conversations").json()
    assert [c["title"] for c in conversations] == ["Summarize my glucose"]

    detail = client.get(f"/chat/conversations/{body['conversation_id']}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][0]["content"] == "Summarize my glucose"


def test_a_conversation_can_be_continued_with_its_history(client, db_session, acting, fake_llms):
    alice = make_user(db_session, "Alice")
    add_reading(db_session, alice)
    acting(alice)

    first = send(client, "First question").json()
    second = send(client, "Second question", first["conversation_id"])

    assert second.status_code == 200
    assert second.json()["conversation_id"] == first["conversation_id"]
    assert "First question" in fake_llms.planner.prompt_text()
    detail = client.get(f"/chat/conversations/{first['conversation_id']}").json()
    assert len(detail["messages"]) == 4


def test_without_a_conversation_id_each_message_starts_a_new_conversation(
    client, db_session, acting, fake_llms
):
    alice = make_user(db_session, "Alice")
    add_reading(db_session, alice)
    acting(alice)

    first = send(client, "One").json()["conversation_id"]
    second = send(client, "Two").json()["conversation_id"]

    assert first != second
    assert len(client.get("/chat/conversations").json()) == 2


def test_users_cannot_see_or_use_each_others_conversations(client, db_session, acting, fake_llms):
    alice = make_user(db_session, "Alice")
    bob = make_user(db_session, "Bob")
    add_reading(db_session, alice)
    acting(alice)
    conversation_id = send(client).json()["conversation_id"]

    acting(bob)
    assert client.get("/chat/conversations").json() == []
    assert client.get(f"/chat/conversations/{conversation_id}").status_code == 404
    assert send(client, "Hello", conversation_id).status_code == 404
    assert client.delete(f"/chat/conversations/{conversation_id}").status_code == 404

    acting(alice)
    detail = client.get(f"/chat/conversations/{conversation_id}").json()
    assert len(detail["messages"]) == 2


def test_deleting_a_conversation_removes_its_messages(client, db_session, acting, fake_llms):
    alice = make_user(db_session, "Alice")
    add_reading(db_session, alice)
    acting(alice)
    conversation_id = send(client).json()["conversation_id"]

    assert client.delete(f"/chat/conversations/{conversation_id}").status_code == 204

    assert client.get(f"/chat/conversations/{conversation_id}").status_code == 404
    assert db_session.query(ChatMessage).count() == 0


@pytest.mark.parametrize(
    "body",
    [
        {"message": ""},
        {"message": "hi", "user_id": 2},
        {"message": "x" * 1001},
        {"message": "hi", "offset_minutes": 9999},
    ],
)
def test_invalid_messages_are_rejected(client, db_session, acting, fake_llms, body):
    alice = make_user(db_session, "Alice")
    acting(alice)

    assert client.post("/chat/messages", json=body).status_code == 422


def test_missing_api_key_gives_a_clear_503(client, db_session, acting, monkeypatch):
    alice = make_user(db_session, "Alice")
    acting(alice)
    monkeypatch.setattr(
        llm_module,
        "get_groq_settings",
        lambda *args, **kwargs: GroqSettings(
            api_key=None, planner_model="x", answer_model="y", timeout_seconds=30
        ),
    )

    response = send(client)

    assert response.status_code == 503
    assert "not set up" in response.json()["detail"]