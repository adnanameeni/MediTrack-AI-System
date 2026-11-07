import re

from app.assistant.prompts import UNSAFE_REPLY_FALLBACK

# Questions the assistant must not answer with a model at all.
_REQUEST_PATTERNS = [
    r"\bdiagnos\w*",
    r"\bdo i have\b",
    r"\bam i (diabetic|hypertensive|pre-?diabetic|sick|ill|at risk)\b",
    r"\bshould i (take|stop|change|increase|reduce|skip|start)\b",
    r"\b(medicine|medicines|medication|medications|drug|drugs|tablet|tablets|pill|pills)\b",
    r"\b(insulin|metformin|dose|dosage|prescri\w*|treatment|treat|cure|therapy)\b",
]

# Things a model reply must never contain.
_REPLY_PATTERNS = [
    r"\byou (have|are suffering from|suffer from|may have|might have|could have|probably have)\b"
    r"[^.]{0,30}\b(diabet\w*|hypertension|hypertensive|hypoglyc\w*|hyperglyc\w*|prediabet\w*|high blood pressure)",
    r"\byou (are|may be|might be|could be|probably are)\b[^.]{0,15}\b(diabetic|hypertensive|prediabetic)",
    r"\b(insulin|metformin|glibenclamide|glipizide|gliclazide|amlodipine|lisinopril|losartan|"
    r"atenolol|metoprolol|statins?|aspirin|medication|medications|medicine|medicines|"
    r"drug|drugs|tablets?|pills?|dosage|dose)\b",
    r"\b\d+(\.\d+)?\s?(mg|mcg|iu|units?)\b",
    r"\b(abnormal|dangerous|unhealthy|alarming|worrying|concerning|critical|too high|too low|"
    r"normal range|healthy range|within normal|in the normal)\b",
]

_REQUEST_RE = re.compile("|".join(f"(?:{p})" for p in _REQUEST_PATTERNS), re.IGNORECASE)
_REPLY_RE = re.compile("|".join(f"(?:{p})" for p in _REPLY_PATTERNS), re.IGNORECASE)


def is_medical_request(text: str) -> bool:
    """True when the question asks for a diagnosis, medicine or treatment advice."""
    return _REQUEST_RE.search(text) is not None


def find_violation(text: str) -> str | None:
    """The first forbidden phrase found in a reply, or None when the reply is clean."""
    match = _REPLY_RE.search(text)
    return match.group(0) if match else None


def is_safe_reply(text: str) -> bool:
    return find_violation(text) is None


def strip_markdown(text: str) -> str:
    """The chat shows plain text, so asterisks, backticks and heading marks are removed."""
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*)\*\s+", r"\1- ", text, flags=re.MULTILINE)
    return text.strip()


def sanitize_reply(text: str) -> str:
    """Return the model's reply (as plain text) if it passes the checks, otherwise a safe fixed message."""
    cleaned = strip_markdown(text)
    if not cleaned or not is_safe_reply(cleaned):
        return UNSAFE_REPLY_FALLBACK
    return cleaned