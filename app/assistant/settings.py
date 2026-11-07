import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Models chosen from the list shown for the owner's own Groq account (2026-11-06).
# Both can be changed in .env without touching code.
DEFAULT_PLANNER_MODEL = "openai/gpt-oss-20b"
DEFAULT_ANSWER_MODEL = "openai/gpt-oss-120b"
DEFAULT_TIMEOUT_SECONDS = 45


@dataclass(frozen=True)
class GroqSettings:
    api_key: str | None = field(repr=False)  # never printed or logged
    planner_model: str
    answer_model: str
    timeout_seconds: int

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


def get_groq_settings(load_env_file: bool = True) -> GroqSettings:
    """Read the Groq settings from the environment (.env). Never raises if the key is missing."""
    if load_env_file:
        load_dotenv()  # does not override variables that are already set

    try:
        timeout = int(os.environ.get("GROQ_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        timeout = DEFAULT_TIMEOUT_SECONDS

    return GroqSettings(
        api_key=os.environ.get("GROQ_API_KEY") or None,
        planner_model=os.environ.get("GROQ_PLANNER_MODEL") or DEFAULT_PLANNER_MODEL,
        answer_model=os.environ.get("GROQ_ANSWER_MODEL") or DEFAULT_ANSWER_MODEL,
        timeout_seconds=max(5, min(timeout, 120)),
    )