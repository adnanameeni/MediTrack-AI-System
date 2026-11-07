from datetime import datetime, timedelta, timezone

from decimal import Decimal



import pytest

from sqlalchemy import select



from app.core.security import hash_password

from app.models import (

    AdminAuditLog,

    BloodPressureReading,

    ChatConversation,

    ChatMessage,

    GlucoseReading,

    ReadingType,

    User,

)

from app.models.user import ROLE_ADMIN, ROLE_USER

from app.services import admin_service

from app.services.admin_service import LastAdminError

from main import app



PASSWORD = "Example-Pass-123"

# Hashing is slow on purpose, so do it once and reuse it for every test user.

PASSWORD_HASH = hash_password(PASSWORD)



PRIVATE_MARKER = "Zq7-private-marker"





# ---------------------------------------------------------------------------

# Helpers

# ---------------------------------------------------------------------------





def make_user(db, email, role=ROLE_USER, active=True, name=None, created_at=None):

    user = User(

        full_name=name or "Example Person",

        email=email,

        hashed_password=PASSWORD_HASH,

        role=role,

        is_active=active,

    )

    if created_at is not None:

        user.created_at = created_at

    db.add(user)

    db.commit()

    return user





def login(client, email):

    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})

    assert response.status_code == 200

    return {"Authorization": "Bearer " + response.json()["access_token"]}





@pytest.fixture

def admin(db_session):

    return make_user(db_session, "admin@example.com", ROLE_ADMIN, name="Alice Admin")





@pytest.fixture

def admin_headers(client, admin):

    return login(client, admin.email)





@pytest.fixture

def normal_headers(client, db_session):

    make_user(db_session, "normal@example.com", name="Nora Normal")

    return login(client, "normal@example.com")





def all_keys(value):

    """Every dictionary key found anywhere inside a JSON value."""

    if isinstance(value, dict):

        for key, item in value.items():

            yield key

            yield from all_keys(item)

    elif isinstance(value, list):

        for item in value:

            yield from all_keys(item)





SENSITIVE_WORDS = ("password", "hash", "token", "secret")





def assert_no_sensitive_data(response):

    body = response.json()

    for key in all_keys(body):

        assert not any(word in key.lower() for word in SENSITIVE_WORDS), key

    assert "$argon2" not in response.text

    assert PASSWORD not in response.text

    assert PRIVATE_MARKER not in response.text





# ---------------------------------------------------------------------------

# Who may use the admin endpoints (backend authorization)

# ---------------------------------------------------------------------------



# Every admin endpoint with a valid example request.

ADMIN_ENDPOINTS = [

    ("GET", "/admin/me", None),

    ("GET", "/admin/overview", None),

    ("GET", "/admin/users", None),

    ("GET", "/admin/users/1", None),

    ("PATCH", "/admin/users/1/role", {"role": "user"}),

    ("PATCH", "/admin/users/1/status", {"is_active": True}),

    ("GET", "/admin/activity", None),

]





def admin_routes_in_the_app():

    """(METHOD, path) for every /admin route, read from the app's own schema."""

    found = set()

    for path, operations in app.openapi()["paths"].items():

        if path.startswith("/admin"):

            for method in operations:

                found.add((method.upper(), path.replace("{user_id}", "1")))

    return found





def test_the_endpoint_list_covers_every_admin_route():

    """If someone adds an admin route, this test forces them to cover it."""

    assert admin_routes_in_the_app() == {(m, p) for m, p, _ in ADMIN_ENDPOINTS}





@pytest.mark.parametrize("method,path,body", ADMIN_ENDPOINTS)

def test_no_token_gets_401(client, method, path, body):

    response = client.request(method, path, json=body)

    assert response.status_code == 401





@pytest.mark.parametrize("method,path,body", ADMIN_ENDPOINTS)

def test_bad_token_gets_401(client, method, path, body):

    headers = {"Authorization": "Bearer not-a-real-token"}

    assert client.request(method, path, json=body, headers=headers).status_code == 401





@pytest.mark.parametrize("method,path,body", ADMIN_ENDPOINTS)

def test_normal_user_gets_403(client, normal_headers, method, path, body):

    response = client.request(method, path, json=body, headers=normal_headers)

    assert response.status_code == 403

    assert response.json() == {"detail": "Administrator access required"}





def test_normal_user_cannot_change_anything(client, db_session, normal_headers):

    target = make_user(db_session, "target@example.com")

    client.patch(

        f"/admin/users/{target.id}/role", json={"role": "admin"}, headers=normal_headers

    )

    client.patch(

        f"/admin/users/{target.id}/status", json={"is_active": False}, headers=normal_headers

    )

    db_session.expire_all()

    assert db_session.get(User, target.id).role == ROLE_USER

    assert db_session.get(User, target.id).is_active is True

    assert db_session.scalar(select(AdminAuditLog)) is None





def test_403_comes_before_input_validation(client, normal_headers):

    """A normal user learns nothing about the endpoint, even with a bad request."""

    response = client.get("/admin/users?limit=9999", headers=normal_headers)

    assert response.status_code == 403

    response = client.patch("/admin/users/1/role", json={"role": "x"}, headers=normal_headers)

    assert response.status_code == 403





def test_admin_can_use_every_endpoint(client, admin_headers, admin):

    for method, path, body in ADMIN_ENDPOINTS:

        if path.endswith("/role") or path.endswith("/status"):

            continue  # changing the admin's own account is tested separately

        path = path.replace("/users/1", f"/users/{admin.id}")

        response = client.request(method, path, json=body, headers=admin_headers)

        assert response.status_code == 200, (method, path)





def test_deactivated_admin_gets_401(client, db_session, admin, admin_headers):

    admin.is_active = False

    db_session.commit()

    assert client.get("/admin/overview", headers=admin_headers).status_code == 401





def test_a_demoted_admin_loses_access_with_the_same_token(

    client, db_session, admin_headers

):

    other = make_user(db_session, "other-admin@example.com", ROLE_ADMIN)

    other_headers = login(client, other.email)

    assert client.get("/admin/overview", headers=other_headers).status_code == 200



    response = client.patch(

        f"/admin/users/{other.id}/role", json={"role": "user"}, headers=admin_headers

    )

    assert response.status_code == 200

    assert client.get("/admin/overview", headers=other_headers).status_code == 403





def test_signup_cannot_create_an_administrator(client, db_session):

    body = {"full_name": "Sneaky", "email": "sneaky@example.com", "password": PASSWORD}

    for extra in ({"role": "admin"}, {"is_admin": True}, {"is_active": True}):

        assert client.post("/auth/signup", json={**body, **extra}).status_code == 422

    assert client.post("/auth/signup", json=body).status_code == 201



    headers = login(client, "sneaky@example.com")

    assert client.get("/admin/overview", headers=headers).status_code == 403

    assert db_session.scalar(select(User).where(User.email == "sneaky@example.com")).role == ROLE_USER





# ---------------------------------------------------------------------------

# Admin profile

# ---------------------------------------------------------------------------





def test_admin_profile(client, admin, admin_headers):

    response = client.get("/admin/me", headers=admin_headers)

    assert response.status_code == 200

    body = response.json()

    assert set(body) == {"id", "full_name", "email", "role", "is_active", "created_at"}

    assert body["id"] == admin.id

    assert body["full_name"] == "Alice Admin"

    assert body["email"] == "admin@example.com"

    assert body["role"] == "admin"

    assert body["is_active"] is True

    assert_no_sensitive_data(response)





# ---------------------------------------------------------------------------

# Overview

# ---------------------------------------------------------------------------





def add_records(db, user, glucose=0, pressure=0, conversations=0):

    for _ in range(glucose):

        db.add(

            GlucoseReading(

                user_id=user.id,

                glucose_value=Decimal("95.5"),

                reading_type=ReadingType.FASTING,

                notes=PRIVATE_MARKER,

            )

        )

    for _ in range(pressure):

        db.add(

            BloodPressureReading(

                user_id=user.id, systolic=120, diastolic=80, notes=PRIVATE_MARKER

            )

        )

    for _ in range(conversations):

        conversation = ChatConversation(user_id=user.id, title=PRIVATE_MARKER)

        db.add(conversation)

        db.flush()

        db.add(

            ChatMessage(

                conversation_id=conversation.id, role="user", content=PRIVATE_MARKER

            )

        )

    db.commit()





def test_overview_totals_are_correct(client, db_session, admin, admin_headers):

    second_admin = make_user(db_session, "admin2@example.com", ROLE_ADMIN)

    make_user(db_session, "inactive-admin@example.com", ROLE_ADMIN, active=False)

    first = make_user(db_session, "u1@example.com")

    second = make_user(db_session, "u2@example.com")

    make_user(db_session, "u3@example.com", active=False)

    add_records(db_session, first, glucose=3, pressure=2, conversations=1)

    add_records(db_session, second, glucose=1, pressure=4, conversations=2)

    add_records(db_session, second_admin, glucose=1)



    response = client.get("/admin/overview", headers=admin_headers)



    assert response.status_code == 200

    body = response.json()

    assert body["users"] == {

        "total": 6,

        "admins": 3,

        "normal_users": 3,

        "active": 4,  # admin, admin2, u1, u2

        "inactive": 2,  # the inactive admin and u3

        "active_admins": 2,

    }

    assert body["records"] == {

        "glucose_readings": 5,

        "blood_pressure_readings": 6,

        "conversations": 3,

    }

    assert_no_sensitive_data(response)





def test_overview_with_only_the_admin(client, admin_headers):

    body = client.get("/admin/overview", headers=admin_headers).json()

    assert body["users"]["total"] == 1

    assert body["users"]["admins"] == 1

    assert body["users"]["normal_users"] == 0

    assert body["records"] == {

        "glucose_readings": 0,

        "blood_pressure_readings": 0,

        "conversations": 0,

    }





def test_overview_recent_registrations_and_trend(client, db_session, admin_headers):

    now = datetime.now(timezone.utc)

    make_user(db_session, "today@example.com")

    make_user(db_session, "three-days@example.com", created_at=now - timedelta(days=3))

    make_user(db_session, "ten-days@example.com", created_at=now - timedelta(days=10))

    make_user(db_session, "forty-days@example.com", created_at=now - timedelta(days=40))



    response = client.get("/admin/overview?days=14", headers=admin_headers)



    body = response.json()

    # Four users made here plus the admin, who also registered just now.

    assert body["users"]["total"] == 5

    recent = body["recent_registrations"]

    assert recent["last_24_hours"] == 2

    assert recent["last_7_days"] == 3

    assert recent["last_30_days"] == 4

    assert recent["latest_registration_at"] is not None



    trend = body["registration_trend"]

    assert trend["days"] == 14

    assert len(trend["points"]) == 14

    today = datetime.fromisoformat(body["generated_at"]).date()

    expected_dates = [(today - timedelta(days=13 - i)).isoformat() for i in range(14)]

    assert [point["date"] for point in trend["points"]] == expected_dates

    counts = {point["date"]: point["count"] for point in trend["points"]}

    assert counts[today.isoformat()] == 2

    assert counts[(today - timedelta(days=3)).isoformat()] == 1

    assert counts[(today - timedelta(days=10)).isoformat()] == 1

    assert trend["total"] == 4  # the 40-day-old user is outside a 14-day window

    assert sum(counts.values()) == 4





def test_overview_trend_days_are_validated(client, admin_headers):

    assert client.get("/admin/overview?days=1", headers=admin_headers).status_code == 200

    assert client.get("/admin/overview?days=365", headers=admin_headers).status_code == 200

    for bad in ("0", "-5", "366", "abc"):

        response = client.get(f"/admin/overview?days={bad}", headers=admin_headers)

        assert response.status_code == 422





def test_overview_service_with_a_fixed_clock(db_session):

    fixed = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)

    make_user(db_session, "a@example.com", created_at=fixed - timedelta(hours=1))

    make_user(db_session, "b@example.com", created_at=fixed - timedelta(days=2))



    overview = admin_service.get_overview(db_session, days=3, now=fixed)



    assert [(p.date.isoformat(), p.count) for p in overview.registration_trend.points] == [

        ("2026-03-08", 1),

        ("2026-03-09", 0),

        ("2026-03-10", 1),

    ]

    assert overview.recent_registrations.last_24_hours == 1

    assert overview.recent_registrations.last_7_days == 2





# ---------------------------------------------------------------------------

# User list: search, filter, pagination

# ---------------------------------------------------------------------------





@pytest.fixture

def people(db_session):

    now = datetime.now(timezone.utc)

    return {

        "ann": make_user(db_session, "ann@example.com", name="Ann Archer",

                         created_at=now - timedelta(days=5)),

        "bob": make_user(db_session, "bob.builder@example.com", name="Bob Builder",

                         created_at=now - timedelta(days=4)),

        "cara": make_user(db_session, "cara@sample.org", name="Cara Cole",

                          created_at=now - timedelta(days=3)),

        "dan": make_user(db_session, "dan@example.com", name="Dan 100% Done",

                         created_at=now - timedelta(days=2)),

        "eve": make_user(db_session, "eve_admin@example.com", ROLE_ADMIN, name="Eve Edwards",

                         created_at=now - timedelta(days=1)),

    }





def emails(response):

    return [item["email"] for item in response.json()["items"]]





def test_list_users_shape_and_order(client, admin_headers, people):

    response = client.get("/admin/users", headers=admin_headers)



    assert response.status_code == 200

    body = response.json()

    assert body["total"] == 6  # five people plus the logged-in admin

    assert body["limit"] == 20

    assert body["offset"] == 0

    # Newest first: the logged-in admin, then Eve, Dan, Cara, Bob, Ann.

    assert emails(response) == [

        "admin@example.com",

        "eve_admin@example.com",

        "dan@example.com",

        "cara@sample.org",

        "bob.builder@example.com",

        "ann@example.com",

    ]

    for item in body["items"]:

        assert set(item) == {"id", "full_name", "email", "role", "is_active", "created_at"}

        assert item["created_at"]

    assert_no_sensitive_data(response)





def test_created_at_has_a_time_zone(client, admin_headers, people):

    item = client.get("/admin/users", headers=admin_headers).json()["items"][0]

    assert datetime.fromisoformat(item["created_at"]).tzinfo is not None





def test_search_by_name_and_email(client, admin_headers, people):

    by_name = client.get("/admin/users?search=Builder", headers=admin_headers)

    assert emails(by_name) == ["bob.builder@example.com"]



    by_email = client.get("/admin/users?search=sample.org", headers=admin_headers)

    assert emails(by_email) == ["cara@sample.org"]



    both = client.get("/admin/users?search=ann", headers=admin_headers)

    assert emails(both) == ["ann@example.com"]





def test_search_ignores_case_and_surrounding_spaces(client, admin_headers, people):

    response = client.get("/admin/users", params={"search": "  CARA "}, headers=admin_headers)

    assert emails(response) == ["cara@sample.org"]





def test_search_with_no_match_is_an_empty_page(client, admin_headers, people):

    body = client.get("/admin/users?search=nobody-like-this", headers=admin_headers).json()

    assert body["items"] == []

    assert body["total"] == 0





def test_search_treats_wildcards_as_plain_text(client, admin_headers, people):

    # A real "100%" appears in one name; "%" alone must not match everybody.

    percent = client.get("/admin/users", params={"search": "100%"}, headers=admin_headers)

    assert emails(percent) == ["dan@example.com"]

    only_percent = client.get("/admin/users", params={"search": "%"}, headers=admin_headers)

    assert emails(only_percent) == ["dan@example.com"]

    # "_" must not act as "any one character": only the Eve address has one.

    underscore = client.get("/admin/users", params={"search": "_"}, headers=admin_headers)

    assert emails(underscore) == ["eve_admin@example.com"]





def test_search_that_looks_like_sql_is_harmless(client, admin_headers, people):

    response = client.get(

        "/admin/users", params={"search": "'; DROP TABLE users; --"}, headers=admin_headers

    )

    assert response.status_code == 200

    assert response.json()["total"] == 0

    assert client.get("/admin/users", headers=admin_headers).json()["total"] == 6





def test_search_is_length_limited(client, admin_headers):

    assert client.get("/admin/users", params={"search": "a" * 100}, headers=admin_headers).status_code == 200

    assert client.get("/admin/users", params={"search": "a" * 101}, headers=admin_headers).status_code == 422





def test_filter_by_role(client, admin_headers, people):

    admins = client.get("/admin/users?role=admin", headers=admin_headers)

    assert sorted(emails(admins)) == ["admin@example.com", "eve_admin@example.com"]

    assert admins.json()["total"] == 2



    users = client.get("/admin/users?role=user", headers=admin_headers)

    assert users.json()["total"] == 4

    assert all(item["role"] == "user" for item in users.json()["items"])





def test_invalid_role_filter_is_rejected(client, admin_headers):

    assert client.get("/admin/users?role=superuser", headers=admin_headers).status_code == 422





def test_search_and_role_filter_together(client, admin_headers, people):

    response = client.get("/admin/users?search=eve&role=admin", headers=admin_headers)

    assert emails(response) == ["eve_admin@example.com"]

    response = client.get("/admin/users?search=eve&role=user", headers=admin_headers)

    assert emails(response) == []





def test_pagination(client, admin_headers, people):

    first = client.get("/admin/users?limit=4&offset=0", headers=admin_headers).json()

    second = client.get("/admin/users?limit=4&offset=4", headers=admin_headers).json()



    assert first["total"] == 6 and second["total"] == 6

    assert first["limit"] == 4 and second["offset"] == 4

    assert len(first["items"]) == 4

    assert len(second["items"]) == 2

    first_ids = {item["id"] for item in first["items"]}

    second_ids = {item["id"] for item in second["items"]}

    assert first_ids.isdisjoint(second_ids)

    assert len(first_ids | second_ids) == 6





def test_pagination_beyond_the_end_is_empty(client, admin_headers, people):

    body = client.get("/admin/users?offset=100", headers=admin_headers).json()

    assert body["items"] == []

    assert body["total"] == 6





def test_pagination_with_a_filter_counts_the_filtered_total(client, admin_headers, people):

    body = client.get("/admin/users?role=user&limit=2&offset=2", headers=admin_headers).json()

    assert body["total"] == 4

    assert len(body["items"]) == 2





@pytest.mark.parametrize(

    "query", ["limit=0", "limit=101", "limit=-1", "offset=-1", "limit=abc", "offset=abc"]

)

def test_bad_pagination_is_rejected(client, admin_headers, query):

    assert client.get(f"/admin/users?{query}", headers=admin_headers).status_code == 422





# ---------------------------------------------------------------------------

# User details

# ---------------------------------------------------------------------------





def test_user_detail_shows_counts_but_no_health_data(client, db_session, admin_headers, people):

    add_records(db_session, people["ann"], glucose=3, pressure=2, conversations=1)



    response = client.get(f"/admin/users/{people['ann'].id}", headers=admin_headers)



    assert response.status_code == 200

    body = response.json()

    assert set(body) == {

        "id", "full_name", "email", "role", "is_active", "created_at",

        "glucose_reading_count", "blood_pressure_reading_count", "conversation_count",

    }

    assert body["email"] == "ann@example.com"

    assert body["glucose_reading_count"] == 3

    assert body["blood_pressure_reading_count"] == 2

    assert body["conversation_count"] == 1

    assert_no_sensitive_data(response)





def test_user_detail_counts_only_that_users_records(client, db_session, admin_headers, people):

    add_records(db_session, people["ann"], glucose=3)

    add_records(db_session, people["bob"], glucose=5)

    body = client.get(f"/admin/users/{people['bob'].id}", headers=admin_headers).json()

    assert body["glucose_reading_count"] == 5





def test_user_detail_unknown_or_invalid_id(client, admin_headers):

    assert client.get("/admin/users/99999", headers=admin_headers).status_code == 404

    assert client.get("/admin/users/abc", headers=admin_headers).status_code == 422





# ---------------------------------------------------------------------------

# Role changes

# ---------------------------------------------------------------------------





def audit_entries(db):

    db.expire_all()

    return list(db.scalars(select(AdminAuditLog).order_by(AdminAuditLog.id)))





def test_admin_can_promote_a_user(client, db_session, admin, admin_headers):

    user = make_user(db_session, "promote@example.com", name="Pat Promote")



    response = client.patch(

        f"/admin/users/{user.id}/role", json={"role": "admin"}, headers=admin_headers

    )



    assert response.status_code == 200

    body = response.json()

    assert body["role"] == "admin"

    assert body["email"] == "promote@example.com"

    assert_no_sensitive_data(response)



    db_session.expire_all()

    assert db_session.get(User, user.id).role == ROLE_ADMIN

    # The newly promoted user can now use the admin endpoints.

    assert client.get("/admin/overview", headers=login(client, user.email)).status_code == 200



    entry = audit_entries(db_session)[0]

    assert entry.action == "admin_promoted"

    assert entry.admin_user_id == admin.id

    assert entry.target_user_id == user.id

    assert entry.detail == "user -> admin"

    assert entry.created_at is not None





def test_admin_can_demote_another_admin(client, db_session, admin, admin_headers):

    other = make_user(db_session, "demote@example.com", ROLE_ADMIN)



    response = client.patch(

        f"/admin/users/{other.id}/role", json={"role": "user"}, headers=admin_headers

    )



    assert response.status_code == 200

    assert response.json()["role"] == "user"

    entry = audit_entries(db_session)[0]

    assert entry.action == "admin_demoted"

    assert entry.admin_user_id == admin.id

    assert entry.target_user_id == other.id

    assert entry.detail == "admin -> user"





def test_role_change_does_not_touch_other_fields(client, db_session, admin_headers):

    user = make_user(db_session, "keep@example.com", name="Kim Keep", active=False)

    before = (user.full_name, user.email, user.hashed_password, user.is_active)



    client.patch(f"/admin/users/{user.id}/role", json={"role": "admin"}, headers=admin_headers)



    db_session.expire_all()

    after = db_session.get(User, user.id)

    assert (after.full_name, after.email, after.hashed_password, after.is_active) == before





def test_setting_the_same_role_changes_nothing_and_logs_nothing(client, db_session, admin_headers):

    user = make_user(db_session, "same@example.com")

    response = client.patch(

        f"/admin/users/{user.id}/role", json={"role": "user"}, headers=admin_headers

    )

    assert response.status_code == 200

    assert response.json()["role"] == "user"

    assert audit_entries(db_session) == []





def test_an_admin_cannot_remove_their_own_admin_rights(

    client, db_session, admin, admin_headers

):

    make_user(db_session, "second-admin@example.com", ROLE_ADMIN)  # not the last admin



    response = client.patch(

        f"/admin/users/{admin.id}/role", json={"role": "user"}, headers=admin_headers

    )



    assert response.status_code == 409

    assert response.json() == {"detail": "You cannot remove your own administrator access"}

    db_session.expire_all()

    assert db_session.get(User, admin.id).role == ROLE_ADMIN

    assert audit_entries(db_session) == []  # a refused action is not logged as done





def test_the_only_admin_cannot_demote_themselves(client, db_session, admin, admin_headers):

    response = client.patch(

        f"/admin/users/{admin.id}/role", json={"role": "user"}, headers=admin_headers

    )

    assert response.status_code == 409

    db_session.expire_all()

    assert db_session.get(User, admin.id).role == ROLE_ADMIN

    assert client.get("/admin/overview", headers=admin_headers).status_code == 200





def test_an_admin_can_keep_their_own_admin_role(client, admin, admin_headers):

    response = client.patch(

        f"/admin/users/{admin.id}/role", json={"role": "admin"}, headers=admin_headers

    )

    assert response.status_code == 200





def test_the_last_active_admin_is_protected_by_the_service(db_session):

    """The service refuses even if the caller is not that admin.



    Through the web API the caller is always another active admin, so this

    rule is a second safety net behind the self-protection rule.

    """

    only_admin = make_user(db_session, "only@example.com", ROLE_ADMIN)

    stranger = make_user(db_session, "stranger@example.com")  # not an admin



    with pytest.raises(LastAdminError):

        admin_service.change_role(db_session, stranger, only_admin.id, ROLE_USER)

    with pytest.raises(LastAdminError):

        admin_service.set_active(db_session, stranger, only_admin.id, False)



    db_session.expire_all()

    assert db_session.get(User, only_admin.id).role == ROLE_ADMIN

    assert db_session.get(User, only_admin.id).is_active is True

    assert audit_entries(db_session) == []





def test_an_inactive_admin_does_not_count_as_a_spare_admin(db_session):

    only_active = make_user(db_session, "active@example.com", ROLE_ADMIN)

    make_user(db_session, "sleeping@example.com", ROLE_ADMIN, active=False)

    stranger = make_user(db_session, "stranger@example.com")



    with pytest.raises(LastAdminError):

        admin_service.change_role(db_session, stranger, only_active.id, ROLE_USER)





def test_an_admin_can_be_demoted_when_another_active_admin_exists(db_session):

    first = make_user(db_session, "first@example.com", ROLE_ADMIN)

    second = make_user(db_session, "second@example.com", ROLE_ADMIN)



    result = admin_service.change_role(db_session, second, first.id, ROLE_USER)



    assert result.role == ROLE_USER





def test_demoting_an_inactive_admin_is_allowed(client, db_session, admin_headers):

    sleeping = make_user(db_session, "sleeping@example.com", ROLE_ADMIN, active=False)

    response = client.patch(

        f"/admin/users/{sleeping.id}/role", json={"role": "user"}, headers=admin_headers

    )

    assert response.status_code == 200





def test_role_change_unknown_user_is_404(client, admin_headers):

    response = client.patch(

        "/admin/users/99999/role", json={"role": "admin"}, headers=admin_headers

    )

    assert response.status_code == 404





@pytest.mark.parametrize(

    "body",

    [

        {},

        {"role": "superuser"},

        {"role": ""},

        {"role": None},

        {"role": 1},

        {"role": "admin", "is_active": False},

        {"role": "admin", "hashed_password": "x"},

        {"Role": "admin"},

    ],

)

def test_role_change_validates_input(client, db_session, admin_headers, body):

    user = make_user(db_session, "victim@example.com")

    response = client.patch(f"/admin/users/{user.id}/role", json=body, headers=admin_headers)

    assert response.status_code == 422

    db_session.expire_all()

    assert db_session.get(User, user.id).role == ROLE_USER

    assert audit_entries(db_session) == []





def test_role_change_with_a_non_numeric_id_is_422(client, admin_headers):

    response = client.patch(

        "/admin/users/abc/role", json={"role": "admin"}, headers=admin_headers

    )

    assert response.status_code == 422





# ---------------------------------------------------------------------------

# Activating and deactivating accounts

# ---------------------------------------------------------------------------





def test_admin_can_deactivate_and_reactivate_a_user(client, db_session, admin, admin_headers):

    user = make_user(db_session, "toggle@example.com")

    user_headers = login(client, user.email)

    assert client.get("/auth/me", headers=user_headers).status_code == 200



    off = client.patch(

        f"/admin/users/{user.id}/status", json={"is_active": False}, headers=admin_headers

    )

    assert off.status_code == 200

    assert off.json()["is_active"] is False

    assert client.get("/auth/me", headers=user_headers).status_code == 401

    login_attempt = client.post(

        "/auth/login", json={"email": user.email, "password": PASSWORD}

    )

    assert login_attempt.status_code == 401



    on = client.patch(

        f"/admin/users/{user.id}/status", json={"is_active": True}, headers=admin_headers

    )

    assert on.status_code == 200

    assert client.get("/auth/me", headers=user_headers).status_code == 200



    actions = [(e.action, e.admin_user_id, e.target_user_id) for e in audit_entries(db_session)]

    assert actions == [

        ("user_deactivated", admin.id, user.id),

        ("user_activated", admin.id, user.id),

    ]





def test_an_admin_cannot_deactivate_themselves(client, db_session, admin, admin_headers):

    response = client.patch(

        f"/admin/users/{admin.id}/status", json={"is_active": False}, headers=admin_headers

    )

    assert response.status_code == 409

    assert response.json() == {"detail": "You cannot deactivate your own account"}

    db_session.expire_all()

    assert db_session.get(User, admin.id).is_active is True

    assert audit_entries(db_session) == []





def test_status_change_to_the_same_value_logs_nothing(client, db_session, admin_headers):

    user = make_user(db_session, "already@example.com")

    response = client.patch(

        f"/admin/users/{user.id}/status", json={"is_active": True}, headers=admin_headers

    )

    assert response.status_code == 200

    assert audit_entries(db_session) == []





@pytest.mark.parametrize(

    "body", [{}, {"is_active": "yes"}, {"is_active": 1}, {"is_active": None}, {"active": False}]

)

def test_status_change_validates_input(client, db_session, admin_headers, body):

    user = make_user(db_session, "strict@example.com")

    response = client.patch(f"/admin/users/{user.id}/status", json=body, headers=admin_headers)

    assert response.status_code == 422

    db_session.expire_all()

    assert db_session.get(User, user.id).is_active is True





def test_status_change_unknown_user_is_404(client, admin_headers):

    response = client.patch(

        "/admin/users/99999/status", json={"is_active": False}, headers=admin_headers

    )

    assert response.status_code == 404





# ---------------------------------------------------------------------------

# Activity log

# ---------------------------------------------------------------------------





def test_activity_is_empty_at_first(client, admin_headers):

    body = client.get("/admin/activity", headers=admin_headers).json()

    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}





def test_activity_lists_actions_with_the_responsible_admin(

    client, db_session, admin, admin_headers

):

    user = make_user(db_session, "audited@example.com", name="Ada Audited")

    client.patch(f"/admin/users/{user.id}/role", json={"role": "admin"}, headers=admin_headers)

    client.patch(f"/admin/users/{user.id}/role", json={"role": "user"}, headers=admin_headers)

    client.patch(f"/admin/users/{user.id}/status", json={"is_active": False}, headers=admin_headers)



    response = client.get("/admin/activity", headers=admin_headers)



    assert response.status_code == 200

    body = response.json()

    assert body["total"] == 3

    # Newest first.

    assert [item["action"] for item in body["items"]] == [

        "user_deactivated",

        "admin_demoted",

        "admin_promoted",

    ]

    newest = body["items"][0]

    assert set(newest) == {"id", "action", "detail", "created_at", "admin", "target"}

    assert newest["admin"] == {

        "id": admin.id, "full_name": "Alice Admin", "email": "admin@example.com",

    }

    assert newest["target"] == {

        "id": user.id, "full_name": "Ada Audited", "email": "audited@example.com",

    }

    assert datetime.fromisoformat(newest["created_at"]).tzinfo is not None

    assert_no_sensitive_data(response)





def test_activity_shows_command_line_actions_without_an_admin(

    client, db_session, admin_headers

):

    user = make_user(db_session, "cli@example.com")

    db_session.add(

        AdminAuditLog(

            admin_user_id=None,

            target_user_id=user.id,

            action="role_changed",

            detail="user -> admin (command line)",

        )

    )

    db_session.commit()



    item = client.get("/admin/activity", headers=admin_headers).json()["items"][0]



    assert item["action"] == "role_changed"

    assert item["admin"] is None

    assert item["target"]["email"] == "cli@example.com"





def test_activity_copes_with_a_deleted_target(client, db_session, admin, admin_headers):

    # A real user is deleted after an action was logged about them. (The old

    # version of this test used an id that never existed, which a real

    # PostgreSQL database correctly refuses.)

    target = make_user(db_session, "to-be-deleted@example.com")

    db_session.add(

        AdminAuditLog(

            admin_user_id=admin.id, target_user_id=target.id, action="role_changed", detail="x"

        )

    )

    db_session.commit()

    db_session.delete(target)

    db_session.commit()

    item = client.get("/admin/activity", headers=admin_headers).json()["items"][0]

    assert item["target"] is None

    assert item["admin"]["id"] == admin.id





def test_activity_pagination_and_action_filter(client, db_session, admin_headers):

    users = [make_user(db_session, f"p{i}@example.com") for i in range(5)]

    for user in users:

        client.patch(f"/admin/users/{user.id}/role", json={"role": "admin"}, headers=admin_headers)

    client.patch(f"/admin/users/{users[0].id}/status", json={"is_active": False}, headers=admin_headers)



    everything = client.get("/admin/activity", headers=admin_headers).json()

    assert everything["total"] == 6



    page_one = client.get("/admin/activity?limit=4", headers=admin_headers).json()

    page_two = client.get("/admin/activity?limit=4&offset=4", headers=admin_headers).json()

    assert len(page_one["items"]) == 4

    assert len(page_two["items"]) == 2

    ids = [item["id"] for item in page_one["items"] + page_two["items"]]

    assert len(set(ids)) == 6



    promotions = client.get("/admin/activity?action=admin_promoted", headers=admin_headers).json()

    assert promotions["total"] == 5

    assert all(item["action"] == "admin_promoted" for item in promotions["items"])



    nothing = client.get("/admin/activity?action=does_not_exist", headers=admin_headers).json()

    assert nothing["items"] == [] and nothing["total"] == 0





@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=abc"])

def test_activity_validates_pagination(client, admin_headers, query):

    assert client.get(f"/admin/activity?{query}", headers=admin_headers).status_code == 422





def test_viewing_data_does_not_create_audit_entries(client, db_session, admin_headers, people):

    client.get("/admin/overview", headers=admin_headers)

    client.get("/admin/users", headers=admin_headers)

    client.get(f"/admin/users/{people['ann'].id}", headers=admin_headers)

    client.get("/admin/activity", headers=admin_headers)

    assert audit_entries(db_session) == []





# ---------------------------------------------------------------------------

# Privacy: administrators never see health records or conversations

# ---------------------------------------------------------------------------





def test_no_admin_response_contains_private_records_or_secrets(

    client, db_session, admin_headers, people

):

    for person in people.values():

        add_records(db_session, person, glucose=2, pressure=2, conversations=1)

    client.patch(

        f"/admin/users/{people['ann'].id}/role", json={"role": "admin"}, headers=admin_headers

    )



    responses = [

        client.get("/admin/me", headers=admin_headers),

        client.get("/admin/overview", headers=admin_headers),

        client.get("/admin/users", headers=admin_headers),

        client.get("/admin/users?search=ann", headers=admin_headers),

        client.get(f"/admin/users/{people['bob'].id}", headers=admin_headers),

        client.get("/admin/activity", headers=admin_headers),

    ]

    for response in responses:

        assert response.status_code == 200

        assert_no_sensitive_data(response)





def test_there_are_no_admin_endpoints_for_readings_or_messages():

    admin_paths = {path for _, path in admin_routes_in_the_app()}

    assert admin_paths  # the check below must not pass on an empty list

    for path in admin_paths:

        for word in ("glucose", "blood", "reading", "message", "conversation", "chat"):

            assert word not in path





# ---------------------------------------------------------------------------

# Existing user endpoints still isolate users, even for administrators

# ---------------------------------------------------------------------------





def test_admins_only_see_their_own_glucose_and_blood_pressure(

    client, db_session, admin, admin_headers, people

):

    add_records(db_session, admin, glucose=1, pressure=1)

    add_records(db_session, people["ann"], glucose=4, pressure=3)

    ann_glucose = db_session.scalar(

        select(GlucoseReading).where(GlucoseReading.user_id == people["ann"].id)

    )

    ann_pressure = db_session.scalar(

        select(BloodPressureReading).where(BloodPressureReading.user_id == people["ann"].id)

    )



    assert len(client.get("/glucose", headers=admin_headers).json()) == 1

    assert len(client.get("/blood-pressure", headers=admin_headers).json()) == 1

    assert client.get(f"/glucose/{ann_glucose.id}", headers=admin_headers).status_code == 404

    assert client.patch(

        f"/glucose/{ann_glucose.id}", json={"notes": "x"}, headers=admin_headers

    ).status_code == 404

    assert client.delete(f"/glucose/{ann_glucose.id}", headers=admin_headers).status_code == 404

    assert client.get(f"/blood-pressure/{ann_pressure.id}", headers=admin_headers).status_code == 404

    assert client.delete(f"/blood-pressure/{ann_pressure.id}", headers=admin_headers).status_code == 404



    db_session.expire_all()

    assert db_session.get(GlucoseReading, ann_glucose.id) is not None

    assert db_session.get(BloodPressureReading, ann_pressure.id) is not None





def test_admins_only_see_their_own_conversations(client, db_session, admin, admin_headers, people):

    add_records(db_session, admin, conversations=1)

    add_records(db_session, people["ann"], conversations=2)

    ann_conversation = db_session.scalar(

        select(ChatConversation).where(ChatConversation.user_id == people["ann"].id)

    )



    listed = client.get("/chat/conversations", headers=admin_headers).json()

    assert len(listed) == 1

    assert (

        client.get(f"/chat/conversations/{ann_conversation.id}", headers=admin_headers).status_code

        == 404

    )

    assert (

        client.delete(f"/chat/conversations/{ann_conversation.id}", headers=admin_headers).status_code

        == 404

    )





def test_admins_only_get_their_own_statistics_and_charts(

    client, db_session, admin, admin_headers, people

):

    add_records(db_session, people["ann"], glucose=4, pressure=4)

    params = {"start": "2000-01-01T00:00:00Z", "end": "2100-01-01T00:00:00Z"}

    # Keep the range within the 366-day limit the app enforces.

    now = datetime.now(timezone.utc)

    params = {

        "start": (now - timedelta(days=30)).isoformat(),

        "end": (now + timedelta(days=1)).isoformat(),

    }



    assert client.get("/stats/glucose", params=params, headers=admin_headers).json()["count"] == 0

    assert client.get("/stats/blood-pressure", params=params, headers=admin_headers).json()["count"] == 0

    assert client.get("/charts/glucose", params=params, headers=admin_headers).json()["points"] == []

    assert client.get("/charts/blood-pressure", params=params, headers=admin_headers).json()["points"] == []





def test_normal_users_still_use_their_own_endpoints(client, normal_headers):

    assert client.get("/auth/me", headers=normal_headers).status_code == 200

    assert client.get("/glucose", headers=normal_headers).status_code == 200

    assert client.get("/blood-pressure", headers=normal_headers).status_code == 200

    assert client.get("/chat/conversations", headers=normal_headers).status_code == 200





def test_auth_me_is_unchanged_for_administrators(client, admin_headers):

    body = client.get("/auth/me", headers=admin_headers).json()

    assert set(body) == {"id", "full_name", "email", "is_active", "created_at"}

