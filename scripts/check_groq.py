"""Checks the Groq setup without sending any health data. Never prints the key."""

from app.assistant.settings import get_groq_settings


def main() -> None:
    settings = get_groq_settings()
    key = settings.api_key or ""

    def safe(text: str) -> str:
        return text.replace(key, "[key hidden]")[:300] if key else text[:300]

    print("Key found in .env:", "yes" if settings.configured else "NO")
    print("Planner model:", settings.planner_model)
    print("Answer model: ", settings.answer_model)
    if not settings.configured:
        print("Add GROQ_API_KEY to .env, restart, and run this again.")
        return

    print("\n1. Models your account can use:")
    available: list[str] = []
    try:
        from groq import Groq

        client = Groq(api_key=key, timeout=settings.timeout_seconds)
        available = sorted(m.id for m in client.models.list().data)
        for model_id in available:
            print("   ", model_id)
    except Exception as error:
        print("   FAILED:", type(error).__name__, "-", safe(str(error)))

    for label, model in (("planner", settings.planner_model), ("answer", settings.answer_model)):
        if available:
            print(f"\nIs the {label} model listed?", "yes" if model in available else "NO")

    print("\n2. Test call to each model (sends only a fake sentence, no health data):")
    from langchain_groq import ChatGroq

    for label, model in (("planner", settings.planner_model), ("answer", settings.answer_model)):
        try:
            llm = ChatGroq(
                model=model,
                api_key=key,
                temperature=0,
                max_tokens=1500,
                reasoning_effort="low",
                timeout=settings.timeout_seconds,
                max_retries=0,
            )
            reply = llm.invoke('Reply with exactly this JSON and nothing else: {"ok": true}')
            text = str(reply.content).strip()
            print(f"    {label} ({model}):", "worked ->" if text else "EMPTY REPLY ->", text[:60])
        except Exception as error:
            print(f"    {label} ({model}): FAILED -", type(error).__name__, "-", safe(str(error)))


if __name__ == "__main__":
    main()