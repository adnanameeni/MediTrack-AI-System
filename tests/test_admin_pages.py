"""Tests for the administrator pages and the login redirect rules.

The redirect itself runs in the browser (auth.js). It asks /admin/me, which
answers 200 only for an administrator, so these tests check that answer for
each kind of account, plus the page files and the wiring between them.
"""

import re
from pathlib import Path

from app.core.security import hash_password
from app.models import User
from app.models.user import ROLE_ADMIN, ROLE_USER

PASSWORD = "Example-Pass-123"
PASSWORD_HASH = hash_password(PASSWORD)

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def make_user(db, email, role=ROLE_USER, active=True, name="Example Person"):
    user = User(
        full_name=name,
        email=email,
        hashed_password=PASSWORD_HASH,
        role=role,
        is_active=active,
    )
    db.add(user)
    db.commit()
    return user


def login(client, email):
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


# ---------------------------------------------------------------------------
# The pages exist
# ---------------------------------------------------------------------------


def test_admin_page_loads(client):
    response = client.get("/admin")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Admin" in response.text
    assert "/static/js/admin.js" in response.text
    assert "/static/css/admin.css" in response.text


def test_admin_page_has_every_required_section(client):
    html = client.get("/admin").text
    for marker in (
        "stat-total",
        "stat-admins",
        "stat-normal",
        "stat-glucose",
        "stat-bp",
        "stat-chats",
        "user-search",
        "user-role",
        "users-body",
        "audit-body",
        "profile-email",
        "ad-logout",
    ):
        assert 'id="%s"' % marker in html, marker


def test_admin_assets_are_served(client):
    assert client.get("/static/js/admin.js").status_code == 200
    assert client.get("/static/css/admin.css").status_code == 200


def test_admin_page_holds_no_private_data(client, db_session):
    make_user(db_session, "secret.person@example.com", name="Secret Person")
    text = client.get("/admin").text
    assert "secret.person@example.com" not in text
    assert "Secret Person" not in text


def test_user_dashboard_page_is_unchanged_and_has_no_admin_links(client):
    html = client.get("/dashboard").text
    assert "glucose-form" in html
    assert "bp-form" in html
    assert "/static/js/admin.js" not in html
    assert 'href="/admin"' not in html


# ---------------------------------------------------------------------------
# Who may use the admin APIs behind the page (what the redirect relies on)
# ---------------------------------------------------------------------------


def test_admin_account_is_recognised_as_administrator(client, db_session):
    make_user(db_session, "boss@example.com", ROLE_ADMIN, name="Boss Admin")
    response = client.get("/admin/me", headers=login(client, "boss@example.com"))
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin"
    assert body["email"] == "boss@example.com"
    assert "hashed_password" not in body
    assert "password" not in body


def test_normal_user_is_not_recognised_as_administrator(client, db_session):
    make_user(db_session, "person@example.com", ROLE_USER)
    headers = login(client, "person@example.com")
    assert client.get("/admin/me", headers=headers).status_code == 403
    # ...but their own normal account still works.
    assert client.get("/auth/me", headers=headers).status_code == 200


def test_normal_user_cannot_use_any_admin_api(client, db_session):
    make_user(db_session, "person@example.com", ROLE_USER)
    target = make_user(db_session, "other@example.com", ROLE_USER)
    headers = login(client, "person@example.com")

    assert client.get("/admin/overview", headers=headers).status_code == 403
    assert client.get("/admin/users", headers=headers).status_code == 403
    assert client.get("/admin/users/%d" % target.id, headers=headers).status_code == 403
    assert client.get("/admin/activity", headers=headers).status_code == 403
    assert (
        client.patch(
            "/admin/users/%d/role" % target.id, json={"role": "admin"}, headers=headers
        ).status_code
        == 403
    )
    assert (
        client.patch(
            "/admin/users/%d/status" % target.id,
            json={"is_active": False},
            headers=headers,
        ).status_code
        == 403
    )
    db_session.refresh(target)
    assert target.role == ROLE_USER
    assert target.is_active is True


def test_logged_out_visitor_gets_401_from_admin_apis(client):
    for path in ("/admin/me", "/admin/overview", "/admin/users", "/admin/activity"):
        assert client.get(path).status_code == 401, path


def test_garbage_token_gets_401(client):
    headers = {"Authorization": "Bearer not-a-real-token"}
    assert client.get("/admin/me", headers=headers).status_code == 401


def test_deactivated_administrator_cannot_log_in(client, db_session):
    make_user(db_session, "gone@example.com", ROLE_ADMIN, active=False)
    response = client.post(
        "/auth/login", json={"email": "gone@example.com", "password": PASSWORD}
    )
    assert response.status_code == 401


def test_demoted_administrator_is_sent_to_the_user_dashboard(client, db_session):
    admin = make_user(db_session, "boss@example.com", ROLE_ADMIN)
    make_user(db_session, "second@example.com", ROLE_ADMIN)
    boss = login(client, "boss@example.com")
    second = login(client, "second@example.com")
    assert client.get("/admin/me", headers=boss).status_code == 200

    response = client.patch(
        "/admin/users/%d/role" % admin.id, json={"role": "user"}, headers=second
    )
    assert response.status_code == 200
    # The same token no longer opens the admin area.
    assert client.get("/admin/me", headers=boss).status_code == 403


# ---------------------------------------------------------------------------
# User management and role changes, as the page performs them
# ---------------------------------------------------------------------------


def test_admin_can_search_filter_view_and_manage_users(client, db_session):
    make_user(db_session, "boss@example.com", ROLE_ADMIN, name="Boss Admin")
    carol = make_user(db_session, "carol@example.com", ROLE_USER, name="Carol Jones")
    make_user(db_session, "dave@example.com", ROLE_USER, name="Dave Smith")
    headers = login(client, "boss@example.com")

    found = client.get("/admin/users?search=carol", headers=headers).json()
    assert [item["email"] for item in found["items"]] == ["carol@example.com"]

    admins = client.get("/admin/users?role=admin", headers=headers).json()
    assert [item["email"] for item in admins["items"]] == ["boss@example.com"]

    detail = client.get("/admin/users/%d" % carol.id, headers=headers).json()
    assert detail["glucose_reading_count"] == 0
    assert "readings" not in detail

    promoted = client.patch(
        "/admin/users/%d/role" % carol.id, json={"role": "admin"}, headers=headers
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"

    deactivated = client.patch(
        "/admin/users/%d/status" % carol.id, json={"is_active": False}, headers=headers
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    log = client.get("/admin/activity", headers=headers).json()
    assert {item["action"] for item in log["items"]} == {
        "admin_promoted",
        "user_deactivated",
    }


def test_admin_cannot_remove_own_access_or_the_last_administrator(client, db_session):
    boss = make_user(db_session, "boss@example.com", ROLE_ADMIN)
    headers = login(client, "boss@example.com")

    demote = client.patch(
        "/admin/users/%d/role" % boss.id, json={"role": "user"}, headers=headers
    )
    assert demote.status_code == 409
    deactivate = client.patch(
        "/admin/users/%d/status" % boss.id, json={"is_active": False}, headers=headers
    )
    assert deactivate.status_code == 409
    db_session.refresh(boss)
    assert boss.role == ROLE_ADMIN
    assert boss.is_active is True


def test_role_change_rejects_bad_input(client, db_session):
    make_user(db_session, "boss@example.com", ROLE_ADMIN)
    target = make_user(db_session, "carol@example.com", ROLE_USER)
    headers = login(client, "boss@example.com")

    assert (
        client.patch(
            "/admin/users/%d/role" % target.id, json={"role": "superuser"}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.patch("/admin/users/99999/role", json={"role": "admin"}, headers=headers).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# The login page script
# ---------------------------------------------------------------------------


def test_login_script_sends_administrators_to_the_admin_dashboard():
    script = (STATIC / "js" / "auth.js").read_text(encoding="utf-8")
    assert '"/admin/me"' in script
    assert 'return "/admin"' in script
    assert '"/dashboard"' in script
    # The old behaviour, a blind jump to /dashboard right after login, is gone.
    assert not re.search(
        r'setItem\(TOKEN_KEY, result\.data\.access_token\);\s*window\.location\.replace\("/dashboard"\)',
        script,
    )


def test_admin_script_checks_the_server_before_showing_anything():
    script = (STATIC / "js" / "admin.js").read_text(encoding="utf-8")
    assert '"/admin/me"' in script
    assert "goToUserDashboard" in script
    assert "innerHTML" not in script  # all text is inserted safely