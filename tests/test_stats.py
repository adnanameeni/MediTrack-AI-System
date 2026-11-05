PASSWORD = "a-good-test-password"

START = "2026-01-01T00:00:00Z"
END = "2026-02-01T00:00:00Z"


def make_user(client, email):
    client.post(
        "/auth/signup",
        json={"full_name": "Test Person", "email": email, "password": PASSWORD},
    )
    token = client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def add_glucose(client, headers, value, when):
    response = client.post(
        "/glucose",
        json={"glucose_value": value, "reading_type": "fasting", "recorded_at": when},
        headers=headers,
    )
    assert response.status_code == 201


def add_pressure(client, headers, systolic, diastolic, when, pulse=None):
    response = client.post(
        "/blood-pressure",
        json={
            "systolic": systolic,
            "diastolic": diastolic,
            "pulse": pulse,
            "recorded_at": when,
        },
        headers=headers,
    )
    assert response.status_code == 201


def glucose_stats(client, headers, start=START, end=END):
    return client.get(
        "/stats/glucose", params={"start": start, "end": end}, headers=headers
    )


def pressure_stats(client, headers, start=START, end=END):
    return client.get(
        "/stats/blood-pressure", params={"start": start, "end": end}, headers=headers
    )


def test_stats_require_login(client):
    params = {"start": START, "end": END}
    assert client.get("/stats/glucose", params=params).status_code == 401
    assert client.get("/stats/blood-pressure", params=params).status_code == 401


def test_glucose_stats_values(client):
    headers = make_user(client, "one@example.com")
    add_glucose(client, headers, 90, "2026-01-05T08:00:00Z")
    add_glucose(client, headers, 100, "2026-01-10T08:00:00Z")
    add_glucose(client, headers, 130, "2026-01-15T08:00:00Z")

    body = glucose_stats(client, headers).json()
    assert body["count"] == 3
    assert float(body["average"]) == 106.67
    assert float(body["minimum"]) == 90.0
    assert float(body["maximum"]) == 130.0


def test_glucose_stats_with_no_readings(client):
    headers = make_user(client, "one@example.com")
    body = glucose_stats(client, headers).json()
    assert body["count"] == 0
    assert body["average"] is None
    assert body["minimum"] is None
    assert body["maximum"] is None


def test_range_start_is_included_and_end_is_excluded(client):
    headers = make_user(client, "one@example.com")
    add_glucose(client, headers, 90, START)
    add_glucose(client, headers, 100, END)
    add_glucose(client, headers, 110, "2025-12-31T23:59:00Z")
    body = glucose_stats(client, headers).json()
    assert body["count"] == 1
    assert float(body["average"]) == 90.0


def test_readings_outside_the_range_are_ignored(client):
    headers = make_user(client, "one@example.com")
    add_glucose(client, headers, 90, "2026-01-05T08:00:00Z")
    add_glucose(client, headers, 200, "2026-06-05T08:00:00Z")
    body = glucose_stats(client, headers).json()
    assert body["count"] == 1
    assert float(body["maximum"]) == 90.0


def test_stats_only_use_the_logged_in_users_readings(client):
    first = make_user(client, "one@example.com")
    second = make_user(client, "two@example.com")
    add_glucose(client, first, 90, "2026-01-05T08:00:00Z")
    add_glucose(client, second, 200, "2026-01-05T09:00:00Z")
    add_pressure(client, first, 120, 80, "2026-01-05T08:00:00Z")
    add_pressure(client, second, 180, 110, "2026-01-05T09:00:00Z")

    mine = glucose_stats(client, first).json()
    assert mine["count"] == 1
    assert float(mine["maximum"]) == 90.0

    mine_bp = pressure_stats(client, first).json()
    assert mine_bp["count"] == 1
    assert mine_bp["maximum_systolic"] == 120


def test_blood_pressure_stats_values(client):
    headers = make_user(client, "one@example.com")
    add_pressure(client, headers, 120, 80, "2026-01-05T08:00:00Z", pulse=60)
    add_pressure(client, headers, 130, 90, "2026-01-06T08:00:00Z", pulse=80)
    add_pressure(client, headers, 140, 70, "2026-01-07T08:00:00Z")

    body = pressure_stats(client, headers).json()
    assert body["count"] == 3
    assert float(body["average_systolic"]) == 130.0
    assert float(body["average_diastolic"]) == 80.0
    assert float(body["average_pulse"]) == 70.0
    assert body["minimum_systolic"] == 120
    assert body["maximum_systolic"] == 140
    assert body["minimum_diastolic"] == 70
    assert body["maximum_diastolic"] == 90


def test_blood_pressure_stats_with_no_readings(client):
    headers = make_user(client, "one@example.com")
    body = pressure_stats(client, headers).json()
    assert body["count"] == 0
    assert body["average_systolic"] is None
    assert body["average_pulse"] is None
    assert body["minimum_systolic"] is None


def test_end_must_be_after_start(client):
    headers = make_user(client, "one@example.com")
    assert glucose_stats(client, headers, start=END, end=START).status_code == 422
    assert glucose_stats(client, headers, start=START, end=START).status_code == 422
    assert pressure_stats(client, headers, start=END, end=START).status_code == 422


def test_range_longer_than_366_days_is_rejected(client):
    headers = make_user(client, "one@example.com")
    too_long = glucose_stats(
        client, headers, start="2025-01-01T00:00:00Z", end="2026-06-01T00:00:00Z"
    )
    assert too_long.status_code == 422


def test_missing_or_invalid_dates_are_rejected(client):
    headers = make_user(client, "one@example.com")
    assert client.get("/stats/glucose", headers=headers).status_code == 422
    bad = glucose_stats(client, headers, start="not-a-date", end=END)
    assert bad.status_code == 422
    assert "not-a-date" not in bad.text