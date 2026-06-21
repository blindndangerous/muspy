from django.urls import reverse


def test_health_endpoint_returns_ok(client):
    response = client.get(reverse("health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_admin_url_is_registered(client):
    response = client.get("/admin/")

    assert response.status_code in {200, 302}
