from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, SECRET_KEY

_password_hasher = PasswordHasher()

# A hash of a throwaway value. Used so a login attempt for an unknown email
# takes about as long as one for a known email.
_DUMMY_HASH = _password_hasher.hash("not-a-real-password")


def hash_password(plain_password: str) -> str:
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return _password_hasher.verify(hashed_password, plain_password)
    except (VerificationError, InvalidHashError):
        return False


def burn_password_check(plain_password: str) -> None:
    verify_password(plain_password, _DUMMY_HASH)


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """Return the user id inside a valid token, or None if it is invalid."""
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None