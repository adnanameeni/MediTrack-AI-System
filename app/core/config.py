import os
from pathlib import Path

from dotenv import load_dotenv

# Reads the project's .env file. Values already set in the environment win,
# so tests can provide their own throwaway values.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

_PLACEHOLDER_KEYS = {"replace-with-a-long-random-value"}
_MIN_SECRET_KEY_LENGTH = 32


def _load_secret_key() -> str:
    key = os.getenv("SECRET_KEY")
    if not key:
        raise RuntimeError("SECRET_KEY is not set. Add it to your .env file.")
    if key in _PLACEHOLDER_KEYS or len(key) < _MIN_SECRET_KEY_LENGTH:
        raise RuntimeError(
            "SECRET_KEY is too weak. Use a random value of at least 32 characters."
        )
    return key


def _load_token_minutes() -> int:
    raw = os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    try:
        minutes = int(raw)
    except ValueError:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be a whole number.") from None
    if minutes <= 0:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES must be greater than zero.")
    return minutes


SECRET_KEY = _load_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = _load_token_minutes()