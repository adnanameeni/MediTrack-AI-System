"""The assistant as a LangGraph graph.

check_request -> (refuse) ----------------------------------------> finish
              -> make_plan -> load_facts -> (no data) --------------> finish
                                         -> explain_data -> check_reply -> finish

The models never see the database, names, emails or notes: only numbers computed here.
"""

import json
from datetime import datetime, timezone
from typing import Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.assistant.health_data import collect_facts, compare_facts, has_data
from app.assistant.llm import Llms
from app.assistant.prompts import (
    ANSWER_SYSTEM_PROMPT,
    DISCLAIMER,
    PLANNER_SYSTEM_PROMPT,
    REFUSAL_MESSAGE,
    UNAVAILABLE_MESSAGE,
    build_answer_prompt,
)
from app.assistant.safety import is_medical_request, sanitize_reply

PeriodName = Literal[
    "today",
    "yesterday",
    "last_7_days",
    "last_30_days",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "all_time",
]

HISTORY_TURNS = 6
HISTORY_CHARS = 500

DEFAULT_COMPARISON = {
    "this_week": "last_week",
    "this_month": "last_month",
    "today": "yesterday",
}

METRIC_TEXT = {
    "glucose": "blood glucose",
    "blood_pressure": "blood pressure",
    "both": "glucose or blood pressure",
}


class Plan(BaseModel):
    intent: Literal["summary", "extremes", "trend", "compare", "general"] = "summary"
    metric: Literal["glucose", "blood_pressure", "both"] = "both"
    period: PeriodName = "last_7_days"
    compare_with: PeriodName | None = None


class State(TypedDict, total=False):
    question: str
    history: list[dict]
    route: str
    plan: dict
    facts: dict | None
    previous_facts: dict | None
    comparison: dict | None
    reply: str


def parse_plan(text: str) -> Plan:
    """Read the planner's JSON. Anything unusable falls back to a safe default plan."""
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        plan = Plan.model_validate(json.loads(text[start:end]))
    except Exception:
        return Plan()

    if plan.intent == "compare":
        if plan.compare_with is None or plan.compare_with == plan.period:
            earlier = DEFAULT_COMPARISON.get(plan.period)
            if earlier is None:
                plan = plan.model_copy(update={"intent": "summary", "compare_with": None})
            else:
                plan = plan.model_copy(update={"compare_with": earlier})
    else:
        plan = plan.model_copy(update={"compare_with": None})
    return plan


def _content(response) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = "".join(
            part if isinstance(part, str) else str(part.get("text", ""))
            for part in content
        )
    return str(content)


def _history_text(history: list[dict]) -> str:
    lines = []
    for item in history[-HISTORY_TURNS:]:
        content = item["content"].replace(DISCLAIMER, "").strip()[:HISTORY_CHARS]
        who = "User" if item["role"] == "user" else "Assistant"
        lines.append(f"{who}: {content}")
    return "\n".join(lines)


def _dump(value: dict | None) -> str | None:
    return None if value is None else json.dumps(value, default=str)


def _insufficient_message(metric: str, facts_list: list[dict]) -> str:
    labels = " and ".join(f["period"]["label"] for f in facts_list)
    return (
        f"I can't answer that yet: you have no recorded {METRIC_TEXT[metric]} readings "
        f"for {labels}. Add readings on your dashboard, or ask about a different period."
    )


def build_assistant_graph(
    db: Session,
    user_id: int,
    offset_minutes: int,
    llms: Llms,
    now: datetime | None = None,
):
    def check_request(state: State) -> dict:
        if is_medical_request(state["question"]):
            return {"route": "refuse", "reply": REFUSAL_MESSAGE}
        return {"route": "continue"}

    def make_plan(state: State) -> dict:
        history = _history_text(state.get("history", []))
        prefix = f"Earlier conversation:\n{history}\n\n" if history else ""
        try:
            response = llms.planner.invoke(
                [
                    SystemMessage(content=PLANNER_SYSTEM_PROMPT),
                    HumanMessage(content=f"{prefix}Question: {state['question']}"),
                ]
            )
            plan = parse_plan(_content(response))
        except Exception:
            plan = Plan()
        return {"plan": plan.model_dump()}

    def load_facts(state: State) -> dict:
        plan = Plan(**state["plan"])
        if plan.intent == "general":
            return {"route": "explain", "facts": None, "previous_facts": None, "comparison": None}

        facts = collect_facts(db, user_id, plan.metric, plan.period, offset_minutes, now)

        if plan.intent == "compare" and plan.compare_with:
            previous = collect_facts(
                db, user_id, plan.metric, plan.compare_with, offset_minutes, now
            )
            missing = [f for f in (facts, previous) if not has_data(f)]
            if missing:
                return {
                    "route": "insufficient",
                    "reply": _insufficient_message(plan.metric, missing),
                }
            return {
                "route": "explain",
                "facts": facts,
                "previous_facts": previous,
                "comparison": compare_facts(facts, previous),
            }

        if not has_data(facts):
            return {
                "route": "insufficient",
                "reply": _insufficient_message(plan.metric, [facts]),
            }
        return {"route": "explain", "facts": facts, "previous_facts": None, "comparison": None}

    def explain_data(state: State) -> dict:
        plan = Plan(**state["plan"])
        prompt = build_answer_prompt(
            question=state["question"],
            intent=plan.intent,
            facts_json=_dump(state.get("facts")),
            previous_json=_dump(state.get("previous_facts")),
            comparison_json=_dump(state.get("comparison")),
            history_text=_history_text(state.get("history", [])),
        )
        try:
            response = llms.answer.invoke(
                [SystemMessage(content=ANSWER_SYSTEM_PROMPT), HumanMessage(content=prompt)]
            )
            text = _content(response).strip()
            if not text:
                raise ValueError("empty reply")
        except Exception:
            # The error text is never shown: it could contain request details.
            return {"reply": UNAVAILABLE_MESSAGE}
        return {"reply": text}

    def check_reply(state: State) -> dict:
        return {"reply": sanitize_reply(state["reply"])}

    def finish(state: State) -> dict:
        return {"reply": f"{state['reply']}\n\n{DISCLAIMER}"}

    graph = StateGraph(State)
    graph.add_node("check_request", check_request)
    graph.add_node("make_plan", make_plan)
    graph.add_node("load_facts", load_facts)
    graph.add_node("explain_data", explain_data)
    graph.add_node("check_reply", check_reply)
    graph.add_node("finish", finish)

    graph.add_edge(START, "check_request")
    graph.add_conditional_edges(
        "check_request",
        lambda state: state["route"],
        {"refuse": "finish", "continue": "make_plan"},
    )
    graph.add_edge("make_plan", "load_facts")
    graph.add_conditional_edges(
        "load_facts",
        lambda state: state["route"],
        {"insufficient": "finish", "explain": "explain_data"},
    )
    graph.add_edge("explain_data", "check_reply")
    graph.add_edge("check_reply", "finish")
    graph.add_edge("finish", END)
    return graph.compile()


def run_assistant(
    db: Session,
    user_id: int,
    question: str,
    offset_minutes: int,
    history: list[dict],
    llms: Llms,
    now: datetime | None = None,
) -> str:
    """Answer one question about this user's own readings and return the reply text."""
    graph = build_assistant_graph(
        db, user_id, offset_minutes, llms, now or datetime.now(timezone.utc)
    )
    result = graph.invoke({"question": question, "history": history})
    return result["reply"]