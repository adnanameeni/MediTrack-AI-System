def test_chat_script_is_served_and_never_writes_html(client):
    response = client.get("/static/js/chat.js")

    assert response.status_code == 200
    text = response.text
    assert "/chat/messages" in text
    assert "/chat/conversations" in text
    assert "innerHTML" not in text
    assert "insertAdjacentHTML" not in text


def test_dashboard_script_loads_all_extra_features_and_shares_the_api_helper(client):
    text = client.get("/static/js/dashboard.js").text

    assert "/static/js/charts.js" in text
    assert "/static/js/report.js" in text
    assert "/static/js/chat.js" in text
    assert "api: api" in text


def test_dashboard_page_is_still_served(client):
    assert client.get("/dashboard").status_code == 200