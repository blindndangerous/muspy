from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from releasewatch.models import Artist, Follow, ReleaseEvent, ReleaseGroup, SyncState


def create_user(username):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password=None,
    )


@pytest.mark.django_db
def test_sync_artist_releases_task_syncs_by_artist_id_and_fans_out_created_events(mocker):
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    group = ReleaseGroup.objects.create(mbid=uuid4(), artist=artist, title="Repeater")
    event = ReleaseEvent.objects.create(release_group=group)
    result = mocker.Mock(event_ids=(event.id,))
    sync = mocker.patch("releasewatch.tasks.sync_artist_releases", return_value=result)
    delay = mocker.patch("releasewatch.tasks.fanout_release_notifications.delay")

    from releasewatch.tasks import sync_artist_releases_task

    sync_artist_releases_task(artist.id)

    sync.assert_called_once_with(artist=artist)
    delay.assert_called_once_with(event.id)


@pytest.mark.django_db
def test_sync_artist_releases_task_skips_recently_synced_artist(mocker):
    artist = Artist.objects.create(mbid=uuid4(), name="Fresh")
    SyncState.objects.create(
        artist=artist,
        sync_type=SyncState.SyncType.RELEASES,
        status=SyncState.Status.SUCCEEDED,
        last_succeeded_at=timezone.now(),
    )
    sync = mocker.patch("releasewatch.tasks.sync_artist_releases")
    delay = mocker.patch("releasewatch.tasks.fanout_release_notifications.delay")

    from releasewatch.tasks import sync_artist_releases_task

    sync_artist_releases_task(artist.id)

    sync.assert_not_called()
    delay.assert_not_called()


@pytest.mark.django_db
def test_fanout_release_notifications_task_fans_out_by_release_event_id(mocker):
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    group = ReleaseGroup.objects.create(mbid=uuid4(), artist=artist, title="Repeater")
    event = ReleaseEvent.objects.create(release_group=group)
    fanout = mocker.patch("releasewatch.tasks.fanout_release_event_notifications")

    from releasewatch.tasks import fanout_release_notifications

    fanout_release_notifications(event.id)

    fanout.assert_called_once_with(release_event=event)


@pytest.mark.django_db
def test_enqueue_due_artist_syncs_enqueues_followed_artists_without_sync_state(mocker):
    user = create_user("scanner-user")
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    Follow.objects.create(user=user, artist=artist)
    delay = mocker.patch("releasewatch.tasks.sync_artist_releases_task.delay")

    from releasewatch.tasks import enqueue_due_artist_syncs

    count = enqueue_due_artist_syncs(batch_size=10)

    assert count == 1
    delay.assert_called_once_with(artist.id)


@pytest.mark.django_db
def test_enqueue_due_artist_syncs_skips_recent_success_and_future_retry(mocker):
    user = create_user("scanner-skip-user")
    fresh_artist = Artist.objects.create(mbid=uuid4(), name="Fresh")
    retry_artist = Artist.objects.create(mbid=uuid4(), name="Retry later")
    ignored_artist = Artist.objects.create(mbid=uuid4(), name="Ignored")
    Follow.objects.create(user=user, artist=fresh_artist)
    Follow.objects.create(user=user, artist=retry_artist)
    Follow.objects.create(user=user, artist=ignored_artist, is_ignored=True)
    SyncState.objects.create(
        artist=fresh_artist,
        sync_type=SyncState.SyncType.RELEASES,
        status=SyncState.Status.SUCCEEDED,
        last_succeeded_at=timezone.now(),
    )
    SyncState.objects.create(
        artist=retry_artist,
        sync_type=SyncState.SyncType.RELEASES,
        status=SyncState.Status.FAILED,
        retry_after=timezone.now() + timezone.timedelta(hours=1),
    )
    delay = mocker.patch("releasewatch.tasks.sync_artist_releases_task.delay")

    from releasewatch.tasks import enqueue_due_artist_syncs

    count = enqueue_due_artist_syncs(batch_size=10)

    assert count == 0
    delay.assert_not_called()


@pytest.mark.django_db
def test_enqueue_due_artist_syncs_enqueues_old_success_and_due_failure_in_order(mocker):
    user = create_user("scanner-order-user")
    old_success = Artist.objects.create(mbid=uuid4(), name="Old success")
    due_failure = Artist.objects.create(mbid=uuid4(), name="Due failure")
    Follow.objects.create(user=user, artist=old_success)
    Follow.objects.create(user=user, artist=due_failure)
    SyncState.objects.create(
        artist=old_success,
        sync_type=SyncState.SyncType.RELEASES,
        status=SyncState.Status.SUCCEEDED,
        last_succeeded_at=timezone.now() - timezone.timedelta(days=2),
    )
    SyncState.objects.create(
        artist=due_failure,
        sync_type=SyncState.SyncType.RELEASES,
        status=SyncState.Status.FAILED,
        retry_after=timezone.now() - timezone.timedelta(minutes=1),
    )
    delay = mocker.patch("releasewatch.tasks.sync_artist_releases_task.delay")

    from releasewatch.tasks import enqueue_due_artist_syncs

    count = enqueue_due_artist_syncs(batch_size=10)

    assert count == 2
    assert [call.args[0] for call in delay.call_args_list] == [
        due_failure.id,
        old_success.id,
    ]
