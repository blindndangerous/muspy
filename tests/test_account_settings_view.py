import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from releasewatch.models import UserProfile

pytestmark = pytest.mark.django_db
TEST_PASSWORD = "test-password"  # noqa: S105
NEW_PASSWORD = "A-django-safe-passphrase-123"  # noqa: S105


@pytest.fixture(autouse=True)
def locmem_cache(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "account-settings-tests",
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


def test_account_settings_requires_login(client):
    response = client.get(reverse("releasewatch:account_settings"))

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_account_settings_get_renders_accessible_forms_and_nav_link(client):
    user = create_user()
    UserProfile.objects.create(user=user, timezone="America/Denver", country="us")
    client.force_login(user)

    response = client.get(reverse("releasewatch:account_settings"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "<h1>Account settings</h1>" in html
    assert 'href="/settings/account/"' in html
    assert ">Account settings</a>" in html
    assert 'for="id_email"' in html
    assert 'for="id_timezone"' in html
    assert 'for="id_country"' in html
    assert 'for="id_old_password"' in html
    assert 'for="id_new_password1"' in html
    assert 'id="id_timezone_helptext"' in html
    assert 'aria-describedby="id_timezone_helptext"' in html
    assert 'value="America/Denver"' in html
    assert 'value="US"' in html


def test_account_settings_updates_email_timezone_and_country(client):
    user = create_user()
    UserProfile.objects.create(user=user)
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:account_settings"),
        {
            "account-submit": "1",
            "email": "new-listener@example.test",
            "timezone": "America/New_York",
            "country": "gb",
        },
    )

    assert response.status_code == 302
    user.refresh_from_db()
    profile = UserProfile.objects.get(user=user)
    assert user.email == "new-listener@example.test"
    assert profile.timezone == "America/New_York"
    assert profile.country == "GB"


def test_account_settings_keeps_email_verification_when_email_unchanged(client):
    user = create_user()
    verified_at = timezone.now()
    UserProfile.objects.create(user=user, email_verified_at=verified_at)
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:account_settings"),
        {
            "account-submit": "1",
            "email": user.email,
            "timezone": "America/Denver",
            "country": "us",
        },
    )

    assert response.status_code == 302
    profile = UserProfile.objects.get(user=user)
    assert profile.email_verified_at == verified_at
    assert profile.timezone == "America/Denver"
    assert profile.country == "US"


def test_account_settings_email_change_clears_email_verification(client):
    user = create_user()
    verified_at = timezone.now()
    UserProfile.objects.create(user=user, email_verified_at=verified_at)
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:account_settings"),
        {
            "account-submit": "1",
            "email": "changed@example.test",
            "timezone": "UTC",
            "country": "",
        },
    )

    assert response.status_code == 302
    profile = UserProfile.objects.get(user=user)
    assert profile.email_verified_at is None


def test_account_settings_changes_password_and_keeps_user_logged_in(client):
    user = create_user()
    UserProfile.objects.create(user=user)
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:account_settings"),
        {
            "password-submit": "1",
            "old_password": TEST_PASSWORD,
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        },
    )

    assert response.status_code == 302
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)
    assert str(client.session["_auth_user_id"]) == str(user.pk)


@override_settings(
    AUTH_PASSWORD_VALIDATORS=[
        {
            "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
            "OPTIONS": {"min_length": 8},
        }
    ]
)
def test_account_settings_rejects_invalid_password_change(client):
    user = create_user()
    UserProfile.objects.create(user=user)
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:account_settings"),
        {
            "password-submit": "1",
            "old_password": TEST_PASSWORD,
            "new_password1": "short",
            "new_password2": "short",
        },
    )

    assert response.status_code == 200
    html = response.content.decode()
    assert "Fix these errors" in html
    assert "This password is too short" in html
    assert 'id="id_new_password2_error"' in html
    assert 'aria-invalid="true"' in html
    assert 'aria-describedby="id_new_password2_helptext id_new_password2_error"' in html
    user.refresh_from_db()
    assert user.check_password(TEST_PASSWORD)


@override_settings(RATE_LIMIT_ACCOUNT_PASSWORD=(1, 60))
def test_account_settings_rate_limits_excessive_password_change_attempts(client):
    user = create_user()
    UserProfile.objects.create(user=user)
    client.force_login(user)

    first_response = client.post(
        reverse("releasewatch:account_settings"),
        {
            "password-submit": "1",
            "old_password": "wrong-password",
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        },
    )
    second_response = client.post(
        reverse("releasewatch:account_settings"),
        {
            "password-submit": "1",
            "old_password": "wrong-password",
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        },
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response["Retry-After"]
    user.refresh_from_db()
    assert user.check_password(TEST_PASSWORD)
