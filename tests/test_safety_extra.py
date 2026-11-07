from app.assistant.prompts import UNSAFE_REPLY_FALLBACK
from app.assistant.safety import find_violation, sanitize_reply


def test_markdown_is_removed_from_replies():
    raw = "**Your recorded data:**\n# Heading\n* first item\n* second item"

    cleaned = sanitize_reply(raw)

    assert "*" not in cleaned and "#" not in cleaned
    assert cleaned.startswith("Your recorded data:")
    assert "- first item" in cleaned


def test_find_violation_names_the_matching_phrase():
    assert "dangerous" in find_violation("Your readings are dangerous.")
    assert find_violation("Your recorded data: 4 readings, average 115.") is None


def test_unsafe_replies_are_still_replaced():
    assert sanitize_reply("You have diabetes.") == UNSAFE_REPLY_FALLBACK
    assert sanitize_reply("   ") == UNSAFE_REPLY_FALLBACK