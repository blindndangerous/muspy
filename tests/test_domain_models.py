import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from releasewatch.models import (
    FeedToken,
    NotificationCadence,
    NotificationPreference,
    UserProfile,
    redact_payload,
)

pytestmark = pytest.mark.django_db


def create_user(username: str = "user"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password=None,
    )


def test_user_profile_defaults_and_email_verification_state():
    user = create_user()

    profile = UserProfile.objects.create(user=user)

    assert profile.timezone == "UTC"
    assert profile.country == ""
    assert profile.email_verified_at is None
    assert profile.email_verified is False

    profile.email_verified_at = timezone.now()
    profile.save(update_fields=["email_verified_at"])

    assert profile.email_verified is True


def test_notification_preference_defaults_to_daily_digest():
    user = create_user()

    preference = NotificationPreference.objects.create(user=user)

    assert preference.cadence == NotificationCadence.DAILY
    assert preference.include_future_releases is True
    assert preference.email_enabled is True


def test_notification_preference_rejects_invalid_cadence():
    user = create_user()
    preference = NotificationPreference(user=user, cadence="bad")

    with pytest.raises(ValidationError):
        preference.full_clean()


def test_feed_token_hash_is_globally_unique_but_user_and_type_can_repeat():
    user = create_user()
    other_user = create_user("other")

    FeedToken.objects.create(
        user=user,
        feed_type=FeedToken.FeedType.RSS,
        token_hash="a" * 64,
    )
    FeedToken.objects.create(
        user=user,
        feed_type=FeedToken.FeedType.RSS,
        token_hash="b" * 64,
    )
    FeedToken.objects.create(
        user=user,
        feed_type=FeedToken.FeedType.ICAL,
        token_hash="c" * 64,
    )

    with pytest.raises(IntegrityError):
        FeedToken.objects.create(
            user=other_user,
            feed_type=FeedToken.FeedType.ICAL,
            token_hash="a" * 64,
        )


def test_feed_token_hash_accepts_valid_sha256_hex():
    user = create_user()
    token = FeedToken(
        user=user,
        feed_type=FeedToken.FeedType.RSS,
        token_hash="a" * 64,
    )

    token.full_clean()


def test_feed_token_hash_rejects_short_sha256_hex():
    user = create_user()
    token = FeedToken(
        user=user,
        feed_type=FeedToken.FeedType.RSS,
        token_hash="a" * 63,
    )

    with pytest.raises(ValidationError):
        token.full_clean()


def test_feed_token_hash_rejects_non_hex_sha256_string():
    user = create_user()
    token = FeedToken(
        user=user,
        feed_type=FeedToken.FeedType.RSS,
        token_hash="g" * 64,
    )

    with pytest.raises(ValidationError):
        token.full_clean()


def test_redact_payload_removes_sensitive_values_recursively():
    payload = {
        "artist": "Example",
        "email": "person@example.test",
        "nested": {
            "access_token": "secret-token",
            "client_secret": "secret-client",
            "contact": {"email": "nested@example.test"},
            "safe": "kept",
        },
        "items": [
            {"api_key": "secret-key"},
            {"email": "list@example.test"},
        ],
    }

    redacted = redact_payload(payload)

    assert redacted == {
        "artist": "Example",
        "email": "[redacted]",
        "nested": {
            "access_token": "[redacted]",
            "client_secret": "[redacted]",
            "contact": {"email": "[redacted]"},
            "safe": "kept",
        },
        "items": [
            {"api_key": "[redacted]"},
            {"email": "[redacted]"},
        ],
    }
