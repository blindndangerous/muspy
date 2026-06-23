import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.urls import reverse

from releasewatch.models import NotificationCadence, NotificationPreference

pytestmark = pytest.mark.django_db
TEST_PASSWORD = "test-password"  # noqa: S105


@pytest.fixture(autouse=True)
def locmem_cache(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "notification-settings-tests",
        }
    }
    caches.close_all()
    cache.clear()
    yield
    cache.clear()
    caches.close_all()


def create_user(username="listener"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password=TEST_PASSWORD,
    )


def test_notification_settings_requires_login(client):
    response = client.get(reverse("releasewatch:notification_settings"))

    assert response.status_code == 302


def test_notification_settings_creates_default_preference(client):
    user = create_user()
    client.force_login(user)

    response = client.get(reverse("releasewatch:notification_settings"))

    assert response.status_code == 200
    assert b"Notification settings" in response.content
    assert NotificationPreference.objects.filter(user=user).exists()


def test_notification_settings_saves_valid_preferences(client):
    user = create_user()
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:notification_settings"),
        {
            "cadence": NotificationCadence.WEEKLY,
            "email_enabled": "on",
        },
    )

    assert response.status_code == 302
    preference = NotificationPreference.objects.get(user=user)
    assert preference.cadence == NotificationCadence.WEEKLY
    assert preference.email_enabled is True
    assert preference.include_future_releases is False


def test_notification_settings_rejects_invalid_cadence(client):
    user = create_user()
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:notification_settings"),
        {"cadence": "bad"},
    )

    assert response.status_code == 200
    assert b"Choose a valid choice" in response.content


def test_notification_settings_rate_limit_returns_429(client, mocker):
    user = create_user()
    client.force_login(user)
    mocker.patch(
        "releasewatch.views.check_rate_limit",
        return_value=mocker.Mock(allowed=False, retry_after_seconds=30),
    )

    response = client.post(
        reverse("releasewatch:notification_settings"),
        {"cadence": NotificationCadence.DAILY},
    )

    assert response.status_code == 429
