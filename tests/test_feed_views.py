from datetime import date
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from releasewatch.models import Artist, DatePrecision, FeedToken, Follow, ReleaseEvent, ReleaseGroup

pytestmark = pytest.mark.django_db
TEST_PASSWORD = "test-password"  # noqa: S105


def create_user(username="listener"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password=TEST_PASSWORD,
    )


def create_event(user, *, title="Repeater", visible=True):
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi", sort_name="Fugazi")
    Follow.objects.create(user=user, artist=artist)
    group = ReleaseGroup.objects.create(mbid=uuid4(), artist=artist, title=title)
    return ReleaseEvent.objects.create(
        release_group=group,
        event_date=date(2026, 6, 22),
        date_precision=DatePrecision.DAY,
        visible=visible,
    )


def test_feed_settings_requires_login(client):
    response = client.get(reverse("releasewatch:feed_settings"))

    assert response.status_code == 302


def test_feed_settings_creates_rss_token_and_shows_url_once(client):
    user = create_user()
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:feed_settings"),
        {"feed_type": FeedToken.FeedType.RSS, "name": "Reader"},
        follow=True,
    )

    token = FeedToken.objects.get(user=user, feed_type=FeedToken.FeedType.RSS)
    html = response.content.decode()
    assert response.status_code == 200
    assert token.token_hash not in html
    assert "/feeds/" in html
    assert "/rss/" in html
    assert 'id="new-feed-url"' in html
    assert "Copy this URL now. It will not be shown again." in html
    assert "Reader" in html


def test_feed_settings_revokes_owned_token(client):
    user = create_user()
    token = FeedToken.objects.create(
        user=user,
        feed_type=FeedToken.FeedType.ICAL,
        token_hash="a" * 64,
        name="Calendar",
    )
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:revoke_feed_token", args=[token.id]),
        follow=True,
    )

    token.refresh_from_db()
    assert response.status_code == 200
    assert token.revoked_at is not None
    assert b"Calendar" in response.content
    assert b"This token is revoked." in response.content


def test_rss_feed_uses_active_token_and_followed_visible_events(client):
    user = create_user()
    event = create_event(user)

    from releasewatch.feeds import create_feed_token

    token = create_feed_token(user=user, feed_type=FeedToken.FeedType.RSS, name="Reader")

    response = client.get(reverse("releasewatch:rss_feed", args=[token]))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/rss+xml")
    assert b"Repeater" in response.content
    assert str(event.id).encode() in response.content
    assert FeedToken.objects.get(user=user).last_used_at is not None


def test_ical_feed_uses_active_token_and_hides_unfollowed_events(client):
    user = create_user()
    other = create_user("other")
    create_event(user, title="Followed")
    create_event(other, title="Hidden")

    from releasewatch.feeds import create_feed_token

    token = create_feed_token(user=user, feed_type=FeedToken.FeedType.ICAL, name="Calendar")

    response = client.get(reverse("releasewatch:ical_feed", args=[token]))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/calendar")
    assert b"SUMMARY:Fugazi - Followed" in response.content
    assert b"Hidden" not in response.content


def test_feed_rejects_revoked_or_wrong_type_token(client):
    user = create_user()

    from releasewatch.feeds import create_feed_token

    token = create_feed_token(user=user, feed_type=FeedToken.FeedType.RSS, name="Reader")
    FeedToken.objects.update(revoked_at=timezone.now())

    assert client.get(reverse("releasewatch:rss_feed", args=[token])).status_code == 404
    assert client.get(reverse("releasewatch:ical_feed", args=[token])).status_code == 404
