import pytest
from sqlalchemy.exc import IntegrityError

from app.assistant.settings import (
    DEFAULT_ANSWER_MODEL,
    DEFAULT_PLANNER_MODEL,
    get_groq_settings,
)
from app.database import Base
from app.models import ChatConversation, ChatMessage, User


def make_user(db, name):
    user = User(full_name=name, email=f"{name.lower()}@example.com", hashed_password="x")
    db.add(user)
    db.commit()
    return user


def test_chat_tables_are_registered():
    assert "chat_conversations" in Base.metadata.tables
    assert "chat_messages" in Base.metadata.tables


def test_conversations_belong_to_one_user_and_hold_messages_in_order(db_session):
    alice = make_user(db_session, "Alice")
    bob = make_user(db_session, "Bob")

    conversation = ChatConversation(user_id=alice.id, title="Glucose week")
    conversation.messages.append(ChatMessage(role="user", content="Hello"))
    conversation.messages.append(ChatMessage(role="assistant", content="Hi"))
    db_session.add(conversation)
    db_session.add(ChatConversation(user_id=bob.id))
    db_session.commit()

    alices = db_session.query(ChatConversation).filter_by(user_id=alice.id).all()
    assert len(alices) == 1
    assert [m.role for m in alices[0].messages] == ["user", "assistant"]
    assert alices[0].created_at is not None
    assert db_session.query(ChatConversation).filter_by(user_id=bob.id).one().title == "New conversation"


def test_deleting_a_conversation_deletes_its_messages(db_session):
    alice = make_user(db_session, "Alice")
    conversation = ChatConversation(user_id=alice.id)
    conversation.messages.append(ChatMessage(role="user", content="Hello"))
    db_session.add(conversation)
    db_session.commit()

    db_session.delete(conversation)
    db_session.commit()

    assert db_session.query(ChatMessage).count() == 0


def test_message_role_must_be_user_or_assistant(db_session):
    alice = make_user(db_session, "Alice")
    conversation = ChatConversation(user_id=alice.id)
    conversation.messages.append(ChatMessage(role="system", content="nope"))
    db_session.add(conversation)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_groq_settings_defaults_and_overrides(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_PLANNER_MODEL", raising=False)
    monkeypatch.delenv("GROQ_ANSWER_MODEL", raising=False)
    monkeypatch.delenv("GROQ_TIMEOUT_SECONDS", raising=False)

    missing = get_groq_settings(load_env_file=False)
    assert missing.configured is False
    assert missing.planner_model == DEFAULT_PLANNER_MODEL
    assert missing.answer_model == DEFAULT_ANSWER_MODEL

    monkeypatch.setenv("GROQ_API_KEY", "fake-test-key")
    monkeypatch.setenv("GROQ_ANSWER_MODEL", "some-other-model")
    monkeypatch.setenv("GROQ_TIMEOUT_SECONDS", "not-a-number")
    configured = get_groq_settings(load_env_file=False)
    assert configured.configured is True
    assert configured.answer_model == "some-other-model"
    assert configured.timeout_seconds == 45


def test_the_api_key_never_appears_in_the_settings_text(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-test-key")
    settings = get_groq_settings(load_env_file=False)
    assert "fake-test-key" not in repr(settings)
    assert "fake-test-key" not in str(settings)