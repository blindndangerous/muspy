from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from releasewatch.models import (
    Artist,
    ArtistAlias,
    FeedToken,
    Follow,
    ImportCandidate,
    ImportRun,
    Invite,
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


def test_invite_tracks_uses_and_expiration():
    creator = create_user("creator")
    invite = Invite.objects.create(
        code="abc123",
        created_by=creator,
        max_uses=2,
        expires_at=timezone.now() + timezone.timedelta(days=1),
    )

    assert invite.can_be_used is True

    invite.uses = 2
    invite.save(update_fields=["uses"])

    assert invite.can_be_used is False

    with pytest.raises(IntegrityError):
        Invite.objects.create(code="overused", max_uses=2, uses=3)


def test_invite_cannot_be_used_when_expired_or_revoked():
    expired = Invite.objects.create(
        code="expired",
        expires_at=timezone.now() - timezone.timedelta(days=1),
    )
    revoked = Invite.objects.create(code="revoked", revoked_at=timezone.now())

    assert expired.can_be_used is False
    assert revoked.can_be_used is False


def test_artist_mbid_is_unique_and_aliases_order_by_locale_then_name():
    artist = Artist.objects.create(
        mbid=uuid4(),
        name="The Example",
        sort_name="Example, The",
    )
    ArtistAlias.objects.create(artist=artist, name="Example", locale="en")
    ArtistAlias.objects.create(artist=artist, name="Ejemplo", locale="es")

    assert list(artist.aliases.values_list("locale", "name")) == [
        ("en", "Example"),
        ("es", "Ejemplo"),
    ]

    with pytest.raises(IntegrityError):
        Artist.objects.create(mbid=artist.mbid, name="Duplicate")


def test_follow_is_unique_per_user_artist_and_can_track_ignored_artist():
    user = create_user("listener")
    artist = Artist.objects.create(mbid=uuid4(), name="Artist")

    Follow.objects.create(user=user, artist=artist, is_ignored=True)

    with pytest.raises(IntegrityError):
        Follow.objects.create(user=user, artist=artist)


def test_import_run_and_candidates_store_review_state():
    user = create_user("importer")
    artist = Artist.objects.create(mbid=uuid4(), name="Imported Artist")
    run = ImportRun.objects.create(
        user=user,
        source=ImportRun.Source.LASTFM,
        status=ImportRun.Status.PENDING_REVIEW,
        raw_payload={"artists": ["Imported Artist"]},
    )

    candidate = ImportCandidate.objects.create(
        import_run=run,
        artist=artist,
        source_name="Imported Artist",
        source_identifier="lastfm:imported-artist",
        review_state=ImportCandidate.ReviewState.PENDING,
    )

    assert candidate.review_state == ImportCandidate.ReviewState.PENDING
    assert run.raw_payload["artists"] == ["Imported Artist"]


def test_import_candidates_allow_multiple_blank_source_identifiers():
    user = create_user("plain-text-importer")
    run = ImportRun.objects.create(
        user=user,
        source=ImportRun.Source.PLAIN_TEXT,
        status=ImportRun.Status.PENDING_REVIEW,
    )

    ImportCandidate.objects.create(import_run=run, source_name="First")
    ImportCandidate.objects.create(import_run=run, source_name="Second")

    assert run.candidates.count() == 2


def test_import_candidates_require_unique_nonblank_source_identifier_per_run():
    user = create_user("identifier-importer")
    first_run = ImportRun.objects.create(user=user, source=ImportRun.Source.LASTFM)
    second_run = ImportRun.objects.create(user=user, source=ImportRun.Source.LASTFM)

    ImportCandidate.objects.create(
        import_run=first_run,
        source_name="First",
        source_identifier="lastfm:artist",
    )
    ImportCandidate.objects.create(
        import_run=second_run,
        source_name="Second",
        source_identifier="lastfm:artist",
    )

    with pytest.raises(IntegrityError):
        ImportCandidate.objects.create(
            import_run=first_run,
            source_name="Duplicate",
            source_identifier="lastfm:artist",
        )
