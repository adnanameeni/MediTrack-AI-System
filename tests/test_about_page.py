
from pathlib import Path

from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_about_page_returns_success():
    response = client.get("/about")

    assert response.status_code == 200


def test_about_page_contains_developer_name():
    response = client.get("/about")

    assert response.status_code == 200
    assert "M. Adnan Ameeni" in response.text


def test_about_page_contains_education():
    response = client.get("/about")

    assert response.status_code == 200
    assert "Computer Software Engineering" in response.text


def test_about_page_contains_github_link():
    response = client.get("/about")

    assert response.status_code == 200
    assert "https://github.com/adnanameeni" in response.text


def test_about_page_contains_meditrack_description():
    response = client.get("/about")

    assert response.status_code == 200
    assert "blood glucose" in response.text
    assert "blood pressure" in response.text


def test_about_page_css_file_exists():
    css_path = Path("app/static/css/about.css")

    assert css_path.exists()
