from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select

from app.core.config import ALGORITHM, SECRET_KEY
from app.models import User

SIGNUP = {
    "full_name": "Test Person",
    "email": "test.person@example.com",
    "password": "a-good-test-password",
}


def signup(client, **overrides):
    return client.post("/auth/signup", json={**SIGNUP, **overrides})


def login(client, email=SIGNUP["email"], password=SIGNUP["password"]):
    return client.post("/auth/login", json={"email": email, "password": password})


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_signup_success_hides_password(client):
    response = signup(client)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == SIGNUP["email"]
    assert "password" not in body
    assert "hashed_password" not in body
    assert SIGNUP["password"] not in response.text


def test_signup_stores_hash_not_plain_password(client, db_session):
    signup(client)
    user = db_session.scalar(select(User))
    assert user.hashed_password != SIGNUP["password"]
    assert user.hashed_password.startswith("$argon2")


def test_duplicate_email_is_rejected(client):
    assert signup(client).status_code == 201
    assert signup(client).status_code == 409


def test_duplicate_email_ignores_letter_case(client):
    signup(client)
    response = signup(client, email="TEST.Person@Example.com")
    assert response.status_code == 409


def test_short_password_rejected_without_echoing_it(client):
    # "Zq7!x" is too short (under 8 characters) and is not a word that could
    # appear in a normal error message, so finding it in the response would
    # mean the submitted password was leaked.
    secret_value = "Zq7!x"
    response = signup(client, password=secret_value)
    assert response.status_code == 422
    assert secret_value not in response.text
    assert "input" not in response.json()["detail"][0]


def test_validation_errors_only_contain_safe_fields(client):
    response = signup(client, password="Zq7!x")
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert len(errors) >= 1
    for error in errors:
        assert set(error.keys()) == {"loc", "msg", "type"}


def test_invalid_email_is_not_echoed(client):
    bad_email = "not-an-email-Zq7marker"
    response = signup(client, email=bad_email)
    assert response.status_code == 422
    assert "Zq7marker" not in response.text


def test_login_validation_error_does_not_echo_password(client):
    secret_value = "Zq7!login-marker"
    # The email field is missing on purpose, so validation fails.
    response = client.post("/auth/login", json={"password": secret_value})
    assert response.status_code == 422
    assert secret_value not in response.text
    assert "Zq7" not in response.text


def test_extra_fields_are_rejected(client):
    response = signup(client, is_active=False)
    assert response.status_code == 422


def test_login_success_and_me(client):
    signup(client)
    response = login(client)
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"

    me = client.get("/auth/me", headers=auth_header(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == SIGNUP["email"]


def test_login_wrong_password_and_unknown_email_look_the_same(client):
    signup(client)
    wrong_password = login(client, password="not-the-password")
    unknown_email = login(client, email="nobody@example.com")
    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_me_without_token_is_401(client):
    assert client.get("/auth/me").status_code == 401


def test_me_with_garbage_token_is_401(client):
    response = client.get("/auth/me", headers=auth_header("not-a-real-token"))
    assert response.status_code == 401


def test_me_with_tampered_token_is_401(client):
    signup(client)
    token = login(client).json()["access_token"]
    tampered = token[:-3] + ("abc" if not token.endswith("abc") else "xyz")
    assert client.get("/auth/me", headers=auth_header(tampered)).status_code == 401


def test_me_with_expired_token_is_401(client):
    signup(client)
    user_id = client.post("/auth/login", json={
        "email": SIGNUP["email"], "password": SIGNUP["password"]
    })
    assert user_id.status_code == 200
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {"sub": "1", "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )
    assert client.get("/auth/me", headers=auth_header(expired)).status_code == 401


def test_token_for_deleted_user_is_401(client, db_session):
    signup(client)
    token = login(client).json()["access_token"]
    db_session.delete(db_session.scalar(select(User)))
    db_session.commit()
    assert client.get("/auth/me", headers=auth_header(token)).status_code == 401


def test_inactive_user_cannot_login_or_use_old_token(client, db_session):
    signup(client)
    token = login(client).json()["access_token"]

    user = db_session.scalar(select(User))
    user.is_active = False
    db_session.commit()

    assert login(client).status_code == 401
    assert client.get("/auth/me", headers=auth_header(token)).status_code == 401


def test_each_user_only_sees_their_own_account(client):
    signup(client)
    signup(client, full_name="Other Person", email="other.person@example.com")
    token = login(client, email="other.person@example.com").json()["access_token"]
    me = client.get("/auth/me", headers=auth_header(token))
    assert me.json()["email"] == "other.person@example.com"