import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.database import get_db
from app.dependencies import require_admin
from app.models.admin_audit import ACTION_ROLE_CHANGED, AdminAuditLog
from app.models.user import ROLE_ADMIN, ROLE_USER, User
from app.routes import auth
from scripts import make_admin
from scripts.add_role_column import add_role_column
from scripts.make_admin import LastAdminError, set_role

PASSWORD = "Example-Pass-123"


def make_user(db, email, role=ROLE_USER, active=True):
    user = User(
        full_name="Example Person",
        email=email,
        hashed_password=hash_password(PASSWORD),
        role=role,
        is_active=active,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def admin_client(db_session):
    """A small app with the real login route and one admin-only test route."""
    app = FastAPI()
    app.include_router(auth.router)

    @app.get("/only-admins")
    def only_admins(user: User = Depends(require_admin)):
        return {"id": user.id}

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def login(client, email):
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


# ---------------------------------------------------------------------------
# The role column and the audit table
# ---------------------------------------------------------------------------


def test_new_users_are_normal_users_by_default(db_session):
    user = User(full_name="Example", email="a@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    assert user.role == ROLE_USER


def test_database_rejects_an_unknown_role(db_session):
    db_session.add(
        User(full_name="Example", email="b@example.com", hashed_password="x", role="superuser")
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_audit_table_exists(db_session):
    assert "admin_audit_log" in inspect(db_session.get_bind()).get_table_names()


# ---------------------------------------------------------------------------
# Public signup can never create an administrator
# ---------------------------------------------------------------------------


def test_signup_cannot_choose_a_role(client, db_session):
    body = {"full_name": "Example", "email": "c@example.com", "password": PASSWORD}

    rejected = client.post("/auth/signup", json={**body, "role": "admin"})
    assert rejected.status_code == 422

    created = client.post("/auth/signup", json=body)
    assert created.status_code == 201
    user = db_session.scalar(select(User).where(User.email == "c@example.com"))
    assert user.role == ROLE_USER


def test_existing_auth_me_response_is_unchanged(client):
    body = {"full_name": "Example", "email": "d@example.com", "password": PASSWORD}
    client.post("/auth/signup", json=body)
    token = client.post(
        "/auth/login", json={"email": body["email"], "password": PASSWORD}
    ).json()["access_token"]

    me = client.get("/auth/me", headers={"Authorization": "Bearer " + token}).json()

    assert set(me) == {"id", "full_name", "email", "is_active", "created_at"}


# ---------------------------------------------------------------------------
# require_admin
# ---------------------------------------------------------------------------


def test_admin_is_allowed(admin_client, db_session):
    make_user(db_session, "admin@example.com", ROLE_ADMIN)
    response = admin_client.get("/only-admins", headers=login(admin_client, "admin@example.com"))
    assert response.status_code == 200


def test_normal_user_gets_403(admin_client, db_session):
    make_user(db_session, "user@example.com")
    response = admin_client.get("/only-admins", headers=login(admin_client, "user@example.com"))
    assert response.status_code == 403
    assert response.json() == {"detail": "Administrator access required"}


def test_no_token_or_bad_token_gets_401(admin_client):
    assert admin_client.get("/only-admins").status_code == 401
    bad = {"Authorization": "Bearer not-a-real-token"}
    assert admin_client.get("/only-admins", headers=bad).status_code == 401


def test_deactivated_admin_gets_401(admin_client, db_session):
    admin = make_user(db_session, "admin2@example.com", ROLE_ADMIN)
    headers = login(admin_client, "admin2@example.com")
    admin.is_active = False
    db_session.commit()
    assert admin_client.get("/only-admins", headers=headers).status_code == 401


def test_role_changes_apply_to_tokens_issued_earlier(admin_client, db_session):
    user = make_user(db_session, "later@example.com")
    headers = login(admin_client, "later@example.com")
    assert admin_client.get("/only-admins", headers=headers).status_code == 403

    user.role = ROLE_ADMIN
    db_session.commit()
    assert admin_client.get("/only-admins", headers=headers).status_code == 200

    user.role = ROLE_USER
    db_session.commit()
    assert admin_client.get("/only-admins", headers=headers).status_code == 403


# ---------------------------------------------------------------------------
# The migration script
# ---------------------------------------------------------------------------


def test_migration_adds_the_column_without_touching_existing_users():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, full_name VARCHAR(200) NOT NULL, "
                "email VARCHAR(255) NOT NULL, hashed_password VARCHAR(255) NOT NULL, "
                "created_at DATETIME, is_active BOOLEAN NOT NULL DEFAULT 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO users (full_name, email, hashed_password, is_active) "
                "VALUES ('Old User', 'old@example.com', 'hash', 1)"
            )
        )

    assert add_role_column(engine) is True
    assert add_role_column(engine) is False  # safe to run again

    with engine.connect() as connection:
        row = connection.execute(text("SELECT email, role, is_active FROM users")).one()
    assert tuple(row) == ("old@example.com", "user", 1)


def test_migration_explains_a_missing_users_table():
    with pytest.raises(RuntimeError, match="create_tables"):
        add_role_column(create_engine("sqlite://"))


# ---------------------------------------------------------------------------
# The make_admin command
# ---------------------------------------------------------------------------


def test_promoting_a_user_writes_an_audit_entry(db_session):
    user = make_user(db_session, "boss@example.com")

    result = set_role(db_session, "  BOSS@example.com ", ROLE_ADMIN)

    assert result.role == ROLE_ADMIN
    entry = db_session.scalar(select(AdminAuditLog))
    assert entry.admin_user_id is None
    assert entry.target_user_id == user.id
    assert entry.action == ACTION_ROLE_CHANGED
    assert "user -> admin" in entry.detail


def test_unknown_email_returns_none(db_session):
    assert set_role(db_session, "nobody@example.com", ROLE_ADMIN) is None


def test_setting_the_same_role_adds_no_audit_entry(db_session):
    make_user(db_session, "same@example.com")
    set_role(db_session, "same@example.com", ROLE_USER)
    assert db_session.scalar(select(AdminAuditLog)) is None


def test_the_last_active_admin_cannot_be_removed(db_session):
    make_user(db_session, "only@example.com", ROLE_ADMIN)

    with pytest.raises(LastAdminError):
        set_role(db_session, "only@example.com", ROLE_USER)

    db_session.expire_all()
    assert db_session.scalar(select(User)).role == ROLE_ADMIN


def test_an_admin_can_be_removed_when_another_active_admin_exists(db_session):
    make_user(db_session, "one@example.com", ROLE_ADMIN)
    make_user(db_session, "two@example.com", ROLE_ADMIN)

    result = set_role(db_session, "one@example.com", ROLE_USER)

    assert result.role == ROLE_USER


# ---------------------------------------------------------------------------
# The command line itself (using the test database, never the real one)
# ---------------------------------------------------------------------------


@pytest.fixture
def use_test_db(db_session, monkeypatch):
    monkeypatch.setattr(make_admin, "SessionLocal", lambda: db_session)


def test_command_promotes_and_prints_a_message(use_test_db, db_session, capsys):
    make_user(db_session, "cli@example.com")

    code = make_admin.main(["CLI@example.com"])

    assert code == 0
    assert "cli@example.com is now an administrator." in capsys.readouterr().out


def test_command_reports_an_unknown_email(use_test_db, capsys):
    assert make_admin.main(["nobody@example.com"]) == 1
    assert "No user with that email" in capsys.readouterr().out


def test_command_refuses_to_revoke_the_last_admin(use_test_db, db_session, capsys):
    make_user(db_session, "solo@example.com", ROLE_ADMIN)

    assert make_admin.main(["solo@example.com", "--revoke"]) == 1
    assert "only active administrator" in capsys.readouterr().out