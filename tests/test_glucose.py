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
    body = {"glucose_value": 95.5, "reading_type": "fasting"}
    body.update(overrides)
    return client.post("/glucose", json=body, headers=headers)


def test_glucose_endpoints_require_login(client):
    body = {"glucose_value": 95.5, "reading_type": "fasting"}
    assert client.get("/glucose").status_code == 401
    assert client.post("/glucose", json=body).status_code == 401
    assert client.get("/glucose/1").status_code == 401
    assert client.patch("/glucose/1", json={"notes": "x"}).status_code == 401
    assert client.delete("/glucose/1").status_code == 401


def test_create_reading(client):
    headers = make_user(client, "one@example.com")
    response = add_reading(client, headers, notes="fake note")
    assert response.status_code == 201
    body = response.json()
    assert float(body["glucose_value"]) == 95.5
    assert body["reading_type"] == "fasting"
    assert body["notes"] == "fake note"
    assert "user_id" not in body


def test_create_reading_defaults_the_time(client):
    headers = make_user(client, "one@example.com")
    body = add_reading(client, headers).json()
    assert body["recorded_at"]


@pytest.mark.parametrize("bad_value", [0, -5, 1001, 95.123, "abc"])
def test_create_rejects_bad_values(client, bad_value):
    headers = make_user(client, "one@example.com")
    response = add_reading(client, headers, glucose_value=bad_value)
    assert response.status_code == 422


def test_create_rejects_bad_reading_type(client):
    headers = make_user(client, "one@example.com")
    response = add_reading(client, headers, reading_type="bedtime")
    assert response.status_code == 422


def test_create_rejects_extra_fields_such_as_user_id(client):
    headers = make_user(client, "one@example.com")
    response = add_reading(client, headers, user_id=999)
    assert response.status_code == 422


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
    add_reading(client, first, glucose_value=90, recorded_at="2026-01-01T08:00:00Z")
    add_reading(client, first, glucose_value=100, recorded_at="2026-02-01T08:00:00Z")
    add_reading(client, second, glucose_value=150, recorded_at="2026-03-01T08:00:00Z")

    mine = client.get("/glucose", headers=first).json()
    assert [float(item["glucose_value"]) for item in mine] == [100.0, 90.0]

    theirs = client.get("/glucose", headers=second).json()
    assert [float(item["glucose_value"]) for item in theirs] == [150.0]


def test_list_pagination(client):
    headers = make_user(client, "one@example.com")
    for day in range(1, 4):
        add_reading(client, headers, recorded_at=f"2026-01-0{day}T08:00:00Z")
    page = client.get("/glucose?limit=2&offset=0", headers=headers).json()
    rest = client.get("/glucose?limit=2&offset=2", headers=headers).json()
    assert len(page) == 2
    assert len(rest) == 1
    assert client.get("/glucose?limit=0", headers=headers).status_code == 422


def test_get_one_reading(client):
    headers = make_user(client, "one@example.com")
    reading_id = add_reading(client, headers).json()["id"]
    response = client.get(f"/glucose/{reading_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == reading_id


def test_other_users_reading_is_404_and_untouched(client):
    owner = make_user(client, "one@example.com")
    other = make_user(client, "two@example.com")
    reading_id = add_reading(client, owner, glucose_value=95).json()["id"]
    url = f"/glucose/{reading_id}"

    assert client.get(url, headers=other).status_code == 404
    assert client.patch(url, json={"glucose_value": 200}, headers=other).status_code == 404
    assert client.delete(url, headers=other).status_code == 404

    still_there = client.get(url, headers=owner)
    assert still_there.status_code == 200
    assert float(still_there.json()["glucose_value"]) == 95.0


def test_update_changes_only_the_sent_fields(client):
    headers = make_user(client, "one@example.com")
    created = add_reading(client, headers, notes="keep me").json()
    url = f"/glucose/{created['id']}"

    response = client.patch(url, json={"glucose_value": 110}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert float(body["glucose_value"]) == 110.0
    assert body["reading_type"] == "fasting"
    assert body["notes"] == "keep me"


def test_update_rejects_null_values_and_empty_body(client):
    headers = make_user(client, "one@example.com")
    reading_id = add_reading(client, headers).json()["id"]
    url = f"/glucose/{reading_id}"
    assert client.patch(url, json={"glucose_value": None}, headers=headers).status_code == 422
    assert client.patch(url, json={"reading_type": None}, headers=headers).status_code == 422
    assert client.patch(url, json={}, headers=headers).status_code == 422


def test_update_can_clear_notes(client):
    headers = make_user(client, "one@example.com")
    reading_id = add_reading(client, headers, notes="remove me").json()["id"]
    response = client.patch(f"/glucose/{reading_id}", json={"notes": None}, headers=headers)
    assert response.status_code == 200
    assert response.json()["notes"] is None


def test_delete_reading(client):
    headers = make_user(client, "one@example.com")
    reading_id = add_reading(client, headers).json()["id"]
    url = f"/glucose/{reading_id}"
    assert client.delete(url, headers=headers).status_code == 204
    assert client.get(url, headers=headers).status_code == 404