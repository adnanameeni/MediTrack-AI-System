import pytest

PASSWORD = "a-good-test-password"


def make_user(client, email):
    client.post(
        "/auth/signup",
        json={"full_name": "Test Person", "email": email, "password": PASSWORD},
    )
    token = client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def add_reading(client, headers, **overrides):
    body = {"systolic": 120, "diastolic": 80}
    body.update(overrides)
    return client.post("/blood-pressure", json=body, headers=headers)


def test_blood_pressure_endpoints_require_login(client):
    body = {"systolic": 120, "diastolic": 80}
    assert client.get("/blood-pressure").status_code == 401
    assert client.post("/blood-pressure", json=body).status_code == 401
    assert client.get("/blood-pressure/1").status_code == 401
    assert client.patch("/blood-pressure/1", json={"notes": "x"}).status_code == 401
    assert client.delete("/blood-pressure/1").status_code == 401


def test_create_reading(client):
    headers = make_user(client, "one@example.com")
    response = add_reading(client, headers, pulse=70, notes="fake note")
    assert response.status_code == 201
    body = response.json()
    assert body["systolic"] == 120
    assert body["diastolic"] == 80
    assert body["pulse"] == 70
    assert body["notes"] == "fake note"
    assert "user_id" not in body


def test_pulse_and_notes_are_optional(client):
    headers = make_user(client, "one@example.com")
    body = add_reading(client, headers).json()
    assert body["pulse"] is None
    assert body["notes"] is None
    assert body["recorded_at"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"systolic": 80, "diastolic": 120},
        {"systolic": 100, "diastolic": 100},
        {"systolic": 0},
        {"diastolic": 0},
        {"systolic": -120},
        {"systolic": 301},
        {"systolic": 120.5},
        {"systolic": "abc"},
        {"pulse": 0},
        {"pulse": -5},
        {"pulse": 301},
    ],
)
def test_create_rejects_bad_values(client, overrides):
    headers = make_user(client, "one@example.com")
    response = add_reading(client, headers, **overrides)
    assert response.status_code == 422


def test_create_rejects_extra_fields_such_as_user_id(client):
    headers = make_user(client, "one@example.com")
    assert add_reading(client, headers, user_id=999).status_code == 422


def test_create_rejects_future_time(client):
    headers = make_user(client, "one@example.com")
    response = add_reading(client, headers, recorded_at="2999-01-01T00:00:00Z")
    assert response.status_code == 422


def test_too_long_notes_rejected_without_echoing_them(client):
    headers = make_user(client, "one@example.com")
    response = add_reading(client, headers, notes="Zq7marker" + "x" * 600)
    assert response.status_code == 422
    assert "Zq7marker" not in response.text


def test_list_shows_only_own_readings_newest_first(client):
    first = make_user(client, "one@example.com")
    second = make_user(client, "two@example.com")
    add_reading(client, first, systolic=110, recorded_at="2026-01-01T08:00:00Z")
    add_reading(client, first, systolic=130, recorded_at="2026-02-01T08:00:00Z")
    add_reading(client, second, systolic=150, recorded_at="2026-03-01T08:00:00Z")

    mine = client.get("/blood-pressure", headers=first).json()
    assert [item["systolic"] for item in mine] == [130, 110]

    theirs = client.get("/blood-pressure", headers=second).json()
    assert [item["systolic"] for item in theirs] == [150]


def test_list_pagination(client):
    headers = make_user(client, "one@example.com")
    for day in range(1, 4):
        add_reading(client, headers, recorded_at=f"2026-01-0{day}T08:00:00Z")
    page = client.get("/blood-pressure?limit=2&offset=0", headers=headers).json()
    rest = client.get("/blood-pressure?limit=2&offset=2", headers=headers).json()
    assert len(page) == 2
    assert len(rest) == 1
    assert client.get("/blood-pressure?limit=0", headers=headers).status_code == 422


def test_get_one_reading(client):
    headers = make_user(client, "one@example.com")
    reading_id = add_reading(client, headers).json()["id"]
    response = client.get(f"/blood-pressure/{reading_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == reading_id


def test_other_users_reading_is_404_and_untouched(client):
    owner = make_user(client, "one@example.com")
    other = make_user(client, "two@example.com")
    reading_id = add_reading(client, owner, systolic=125).json()["id"]
    url = f"/blood-pressure/{reading_id}"

    assert client.get(url, headers=other).status_code == 404
    assert client.patch(url, json={"systolic": 200}, headers=other).status_code == 404
    assert client.delete(url, headers=other).status_code == 404

    still_there = client.get(url, headers=owner)
    assert still_there.status_code == 200
    assert still_there.json()["systolic"] == 125


def test_update_changes_only_the_sent_fields(client):
    headers = make_user(client, "one@example.com")
    created = add_reading(client, headers, pulse=70, notes="keep me").json()
    url = f"/blood-pressure/{created['id']}"

    response = client.patch(url, json={"systolic": 135}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["systolic"] == 135
    assert body["diastolic"] == 80
    assert body["pulse"] == 70
    assert body["notes"] == "keep me"


def test_update_rejects_null_values_and_empty_body(client):
    headers = make_user(client, "one@example.com")
    reading_id = add_reading(client, headers).json()["id"]
    url = f"/blood-pressure/{reading_id}"
    assert client.patch(url, json={"systolic": None}, headers=headers).status_code == 422
    assert client.patch(url, json={"diastolic": None}, headers=headers).status_code == 422
    assert client.patch(url, json={}, headers=headers).status_code == 422


def test_update_cannot_break_the_systolic_diastolic_rule(client):
    headers = make_user(client, "one@example.com")
    reading_id = add_reading(client, headers).json()["id"]
    url = f"/blood-pressure/{reading_id}"

    # Both sent together, in the wrong order.
    both = client.patch(url, json={"systolic": 70, "diastolic": 90}, headers=headers)
    assert both.status_code == 422
    # Only one sent, which would break the rule against the saved value (80).
    only_one = client.patch(url, json={"systolic": 75}, headers=headers)
    assert only_one.status_code == 422

    unchanged = client.get(url, headers=headers).json()
    assert unchanged["systolic"] == 120
    assert unchanged["diastolic"] == 80


def test_update_can_clear_pulse_and_notes(client):
    headers = make_user(client, "one@example.com")
    reading_id = add_reading(client, headers, pulse=70, notes="remove me").json()["id"]
    response = client.patch(
        f"/blood-pressure/{reading_id}",
        json={"pulse": None, "notes": None},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["pulse"] is None
    assert response.json()["notes"] is None


def test_delete_reading(client):
    headers = make_user(client, "one@example.com")
    reading_id = add_reading(client, headers).json()["id"]
    url = f"/blood-pressure/{reading_id}"
    assert client.delete(url, headers=headers).status_code == 204
    assert client.get(url, headers=headers).status_code == 404