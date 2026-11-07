import os
from dataclasses import dataclass
from typing import Any

from app.assistant.settings import get_groq_settings


class LlmNotConfigured(Exception):
    """GROQ_API_KEY is missing."""


@dataclass(frozen=True)
class Llms:
    planner: Any  # anything with .invoke(messages) -> object with .content
    answer: Any


def build_llms() -> Llms:
    settings = get_groq_settings()
    if not settings.configured:
        raise LlmNotConfigured()

    # Make sure no data is ever sent to LangChain's optional tracing service.
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"

    from langchain_groq import ChatGroq

    # These models think before they write; the thinking uses part of max_tokens,
    # so the limits are generous and the thinking effort is kept low.
    planner = ChatGroq(
        model=settings.planner_model,
        api_key=settings.api_key,
        temperature=0,
        max_tokens=1500,
        reasoning_effort="low",
        timeout=settings.timeout_seconds,
        max_retries=1,
    )
    answer = ChatGroq(
        model=settings.answer_model,
        api_key=settings.api_key,
        temperature=0.2,
        max_tokens=3000,
        reasoning_effort="low",
        timeout=settings.timeout_seconds,
        max_retries=1,
    )
    return Llms(planner=planner, answer=answer)