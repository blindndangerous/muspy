from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from releasewatch.models import (
    Artist,
    Follow,
    Notification,
    NotificationCadence,
    NotificationPreference,
    ReleaseEvent,
    ReleaseGroup,
)


def create_user(username):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password=None,
    )


def create_release_event(*, event_date=date(2026, 6, 22), notifiable=True):
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    group = ReleaseGroup.objects.create(mbid=uuid4(), artist=artist, title="Repeater")
    return ReleaseEvent.objects.create(
        release_group=group,
        event_date=event_date,
        date_precision="day" if event_date else "",
        notifiable=notifiable,
    )


@pytest.mark.django_db
def test_fanout_release_event_notifications_creates_daily_notifications_by_default():
    event = create_release_event()
    user = create_user("daily-user")
    Follow.objects.create(user=user, artist=event.release_group.artist)

    from releasewatch.notifications import fanout_release_event_notifications

    result = fanout_release_event_notifications(release_event=event)

    notification = Notification.objects.get(user=user, release_event=event)
    assert result.created_count == 1
    assert notification.status == Notification.Status.PENDING
    assert notification.cadence_bucket.startswith("daily:")


@pytest.mark.django_db
def test_fanout_release_event_notifications_respects_weekly_and_instant_preferences():
    event = create_release_event()
    weekly_user = create_user("weekly-user")
    instant_user = create_user("instant-user")
    Follow.objects.create(user=weekly_user, artist=event.release_group.artist)
    Follow.objects.create(user=instant_user, artist=event.release_group.artist)
    NotificationPreference.objects.create(user=weekly_user, cadence=NotificationCadence.WEEKLY)
    NotificationPreference.objects.create(user=instant_user, cadence=NotificationCadence.INSTANT)

    from releasewatch.notifications import fanout_release_event_notifications

    fanout_release_event_notifications(release_event=event, now=datetime(2026, 6, 22, tzinfo=UTC))

    buckets = set(Notification.objects.values_list("cadence_bucket", flat=True))
    assert f"instant:{event.id}" in buckets
    assert "weekly:2026-W26" in buckets


@pytest.mark.django_db
def test_fanout_release_event_notifications_skips_off_disabled_and_ignored_users():
    event = create_release_event()
    off_user = create_user("off-user")
    disabled_user = create_user("disabled-user")
    ignored_user = create_user("ignored-user")
    Follow.objects.create(user=off_user, artist=event.release_group.artist)
    Follow.objects.create(user=disabled_user, artist=event.release_group.artist)
    Follow.objects.create(user=ignored_user, artist=event.release_group.artist, is_ignored=True)
    NotificationPreference.objects.create(user=off_user, cadence=NotificationCadence.OFF)
    NotificationPreference.objects.create(user=disabled_user, email_enabled=False)

    from releasewatch.notifications import fanout_release_event_notifications

    result = fanout_release_event_notifications(release_event=event)

    assert result.created_count == 0
    assert result.skipped_count == 3
    assert Notification.objects.count() == 0


@pytest.mark.django_db
def test_fanout_release_event_notifications_respects_future_release_preference():
    event = create_release_event(event_date=date(2026, 7, 1))
    user = create_user("future-release-user")
    Follow.objects.create(user=user, artist=event.release_group.artist)
    NotificationPreference.objects.create(user=user, include_future_releases=False)

    from releasewatch.notifications import fanout_release_event_notifications

    result = fanout_release_event_notifications(
        release_event=event,
        now=datetime(2026, 6, 22, tzinfo=UTC),
    )

    assert result.created_count == 0
    assert result.skipped_count == 1
    assert Notification.objects.count() == 0


@pytest.mark.django_db
def test_fanout_release_event_notifications_is_idempotent():
    event = create_release_event()
    user = create_user("dedupe-user")
    Follow.objects.create(user=user, artist=event.release_group.artist)

    from releasewatch.notifications import fanout_release_event_notifications

    first = fanout_release_event_notifications(release_event=event)
    second = fanout_release_event_notifications(release_event=event)

    assert first.created_count == 1
    assert second.existing_count == 1
    assert Notification.objects.count() == 1


@pytest.mark.django_db
def test_fanout_release_event_notifications_skips_non_notifiable_events():
    event = create_release_event(event_date=None, notifiable=False)
    user = create_user("undated-user")
    Follow.objects.create(user=user, artist=event.release_group.artist)

    from releasewatch.notifications import fanout_release_event_notifications

    result = fanout_release_event_notifications(release_event=event)

    assert result.created_count == 0
    assert result.skipped_count == 1
    assert Notification.objects.count() == 0
