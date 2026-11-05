def test_home_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "MediTrack AI" in response.text
    assert "login-form" in response.text


def test_dashboard_page_loads(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "Dashboard" in response.text
    assert "glucose-form" in response.text
    assert "bp-form" in response.text


def test_static_files_are_served(client):
    assert client.get("/static/css/style.css").status_code == 200
    assert client.get("/static/js/auth.js").status_code == 200
    assert client.get("/static/js/dashboard.js").status_code == 200


def test_missing_static_file_is_404(client):
    assert client.get("/static/does-not-exist.js").status_code == 404


def test_env_file_is_not_reachable_through_static(client):
    assert client.get("/static/.env").status_code == 404
    assert client.get("/static/../.env").status_code == 404