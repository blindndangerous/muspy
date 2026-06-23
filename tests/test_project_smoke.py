from django.urls import reverse


def test_wsgi_and_asgi_apps_import():
    from config.asgi import application as asgi_application
    from config.wsgi import application as wsgi_application

    assert asgi_application is not None
    assert wsgi_application is not None


def test_health_endpoint_returns_ok(client):
    response = client.get(reverse("health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_admin_url_is_registered(client):
    response = client.get("/admin/")

    assert response.status_code in {200, 302}


def test_health_endpoint_does_not_warn_about_missing_static_root(client, recwarn):
    response = client.get(reverse("health"))

    assert response.status_code == 200
    assert not [
        warning
        for warning in recwarn
        if "No directory at:" in str(warning.message)
        and "staticfiles" in str(warning.message)
    ]
