import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse

from config import settings as app_settings
from releasewatch.models import NotificationPreference, UserProfile

pytestmark = pytest.mark.django_db


def create_user(username="listener"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password=None,
    )


def test_unsubscribe_token_generation_round_trips_user():
    user = create_user()

    from releasewatch.notifications import make_unsubscribe_token, user_for_unsubscribe_token

    token = make_unsubscribe_token(user)

    assert user_for_unsubscribe_token(token) == user


def test_unsubscribe_get_valid_token_shows_confirmation_without_disabling_email(client):
    user = create_user()
    preference = NotificationPreference.objects.create(user=user, email_enabled=True)

    from releasewatch.notifications import make_unsubscribe_token

    response = client.get(
        reverse("releasewatch:email_unsubscribe", args=[make_unsubscribe_token(user)])
    )

    preference.refresh_from_db()
    assert response.status_code == 200
    assert preference.email_enabled is True
    assert "confirm unsubscribe" in response.content.decode().lower()


def test_unsubscribe_post_valid_token_disables_email_notifications(client):
    user = create_user()
    preference = NotificationPreference.objects.create(user=user, email_enabled=True)

    from releasewatch.notifications import make_unsubscribe_token

    response = client.post(
        reverse("releasewatch:email_unsubscribe", args=[make_unsubscribe_token(user)])
    )

    preference.refresh_from_db()
    assert response.status_code == 200
    assert preference.email_enabled is False
    assert "unsubscribed" in response.content.decode().lower()


def test_unsubscribe_invalid_token_returns_controlled_404_without_account_data(client):
    user = create_user()
    NotificationPreference.objects.create(user=user, email_enabled=True)

    response = client.get(reverse("releasewatch:email_unsubscribe", args=["not-a-token"]))

    assert response.status_code == 404
    body = response.content.decode()
    assert user.email not in body
    assert user.username not in body


def test_unsubscribe_invalid_post_returns_controlled_404_without_account_data(client):
    user = create_user()
    NotificationPreference.objects.create(user=user, email_enabled=True)

    response = client.post(reverse("releasewatch:email_unsubscribe", args=["not-a-token"]))

    assert response.status_code == 404
    body = response.content.decode()
    assert user.email not in body
    assert user.username not in body


def test_public_base_url_uses_env_value_in_production(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://muspy.example/")

    assert (
        app_settings._public_base_url(debug=False, running_tests=False)
        == "https://muspy.example"
    )


def test_public_base_url_requires_env_outside_debug_or_tests(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)

    with pytest.raises(ImproperlyConfigured, match="PUBLIC_BASE_URL"):
        app_settings._public_base_url(debug=False, running_tests=False)


def test_public_base_url_rejects_localhost_outside_debug_or_tests(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://localhost:8000")

    with pytest.raises(ImproperlyConfigured, match="PUBLIC_BASE_URL"):
        app_settings._public_base_url(debug=False, running_tests=False)


def test_email_verification_valid_token_sets_verified_timestamp(client):
    user = create_user()
    profile = UserProfile.objects.create(user=user, email_verified_at=None)

    from releasewatch.notifications import make_email_verification_token

    response = client.get(
        reverse("releasewatch:verify_email", args=[make_email_verification_token(user)])
    )

    profile.refresh_from_db()
    assert response.status_code == 200
    assert profile.email_verified_at is not None
    assert "verified" in response.content.decode().lower()


def test_email_verification_invalid_token_returns_controlled_404_without_account_data(client):
    user = create_user()
    UserProfile.objects.create(user=user, email_verified_at=None)

    response = client.get(reverse("releasewatch:verify_email", args=["not-a-token"]))

    assert response.status_code == 404
    body = response.content.decode()
    assert user.email not in body
    assert user.username not in body
