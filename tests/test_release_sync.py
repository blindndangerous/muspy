from dataclasses import dataclass
from datetime import date
from uuid import uuid4

import pytest
from django.utils import timezone

from releasewatch.models import (
    Artist,
    DatePrecision,
    Release,
    ReleaseEvent,
    ReleaseGroup,
    SyncState,
)
from releasewatch.upstreams import UpstreamRateLimited, UpstreamRelease, UpstreamReleaseGroup


@dataclass
class FakeMusicBrainzClient:
    release_groups: list[UpstreamReleaseGroup]
    releases_by_group: dict[str, list[list[UpstreamRelease]]]
    closed: bool = False

    def browse_release_groups(self, artist_mbid, *, limit=100, offset=0):
        if offset:
            return []
        return self.release_groups

    def browse_releases_by_release_group(
        self,
        release_group_mbid,
        *,
        status="official",
        limit=100,
        offset=0,
    ):
        pages = self.releases_by_group.get(release_group_mbid, [])
        if offset >= len(pages):
            return []
        return pages[offset]

    def close(self):
        self.closed = True


def release_group_payload(mbid, title="Repeater", first_release_date=date(1990, 4, 1)):
    return UpstreamReleaseGroup(
        mbid=str(mbid),
        title=title,
        primary_type="Album",
        secondary_types=[],
        first_release_date=first_release_date,
        first_release_precision=DatePrecision.DAY if first_release_date else "",
        raw_payload={"id": str(mbid), "title": title},
    )


def release_payload(mbid, *, country="US", release_date=date(1990, 4, 19)):
    return UpstreamRelease(
        mbid=str(mbid),
        country=country,
        release_date=release_date,
        release_date_precision=DatePrecision.DAY if release_date else "",
        status="Official",
        media_format="CD",
        raw_payload={"id": str(mbid), "country": country},
    )


@pytest.mark.django_db
def test_sync_artist_releases_upserts_release_groups_releases_and_events():
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    group_mbid = uuid4()
    release_mbid = uuid4()
    client = FakeMusicBrainzClient(
        release_groups=[release_group_payload(group_mbid)],
        releases_by_group={str(group_mbid): [[release_payload(release_mbid)]]},
    )

    from releasewatch.sync import sync_artist_releases

    result = sync_artist_releases(artist=artist, client=client)

    group = ReleaseGroup.objects.get(mbid=group_mbid)
    release = Release.objects.get(mbid=release_mbid)
    event = ReleaseEvent.objects.get(release=release)
    sync_state = SyncState.objects.get(artist=artist, sync_type=SyncState.SyncType.RELEASES)
    assert result.release_groups_created == 1
    assert result.releases_created == 1
    assert result.events_created == 1
    assert group.artist == artist
    assert release.release_group == group
    assert event.country == "US"
    assert event.event_date == date(1990, 4, 19)
    assert event.notifiable is True
    assert sync_state.status == SyncState.Status.SUCCEEDED
    assert sync_state.last_succeeded_at is not None


@pytest.mark.django_db
def test_sync_artist_releases_is_idempotent():
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    group_mbid = uuid4()
    release_mbid = uuid4()
    client = FakeMusicBrainzClient(
        release_groups=[release_group_payload(group_mbid)],
        releases_by_group={str(group_mbid): [[release_payload(release_mbid)]]},
    )

    from releasewatch.sync import sync_artist_releases

    sync_artist_releases(artist=artist, client=client)
    second = sync_artist_releases(artist=artist, client=client)

    assert second.release_groups_updated == 1
    assert second.releases_updated == 1
    assert second.events_updated == 1
    assert ReleaseGroup.objects.count() == 1
    assert Release.objects.count() == 1
    assert ReleaseEvent.objects.count() == 1


@pytest.mark.django_db
def test_sync_artist_releases_creates_fallback_group_event_when_no_releases_exist():
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    group_mbid = uuid4()
    client = FakeMusicBrainzClient(
        release_groups=[release_group_payload(group_mbid)],
        releases_by_group={str(group_mbid): [[]]},
    )

    from releasewatch.sync import sync_artist_releases

    result = sync_artist_releases(artist=artist, client=client)

    event = ReleaseEvent.objects.get(release__isnull=True)
    assert result.events_created == 1
    assert event.release_group.mbid == group_mbid
    assert event.event_date == date(1990, 4, 1)
    assert event.notifiable is True


@pytest.mark.django_db
def test_sync_artist_releases_marks_undated_events_visible_but_not_notifiable():
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    group_mbid = uuid4()
    release_mbid = uuid4()
    client = FakeMusicBrainzClient(
        release_groups=[release_group_payload(group_mbid, first_release_date=None)],
        releases_by_group={str(group_mbid): [[release_payload(release_mbid, release_date=None)]]},
    )

    from releasewatch.sync import sync_artist_releases

    sync_artist_releases(artist=artist, client=client)

    event = ReleaseEvent.objects.get()
    assert event.visible is True
    assert event.notifiable is False
    assert event.event_date is None


@pytest.mark.django_db
def test_sync_artist_releases_skips_invalid_release_rows():
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    group_mbid = uuid4()
    client = FakeMusicBrainzClient(
        release_groups=[release_group_payload(group_mbid)],
        releases_by_group={
            str(group_mbid): [
                [
                    UpstreamRelease(
                        mbid="not-a-uuid",
                        country="US",
                        release_date=date(1990, 4, 19),
                        release_date_precision=DatePrecision.DAY,
                        status="Official",
                        media_format="CD",
                        raw_payload={},
                    )
                ]
            ]
        },
    )

    from releasewatch.sync import sync_artist_releases

    result = sync_artist_releases(artist=artist, client=client)

    assert result.skipped_count == 1
    assert Release.objects.count() == 0


@pytest.mark.django_db
def test_sync_artist_releases_records_rate_limit_failure_and_retry_time():
    class RateLimitedClient(FakeMusicBrainzClient):
        def browse_release_groups(self, artist_mbid, *, limit=100, offset=0):
            raise UpstreamRateLimited(
                "musicbrainz rate limited",
                provider="musicbrainz",
                status_code=503,
                payload={},
            )

    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    client = RateLimitedClient(release_groups=[], releases_by_group={})

    from releasewatch.sync import ReleaseSyncError, sync_artist_releases

    with pytest.raises(ReleaseSyncError):
        sync_artist_releases(artist=artist, client=client)

    sync_state = SyncState.objects.get(artist=artist, sync_type=SyncState.SyncType.RELEASES)
    assert sync_state.status == SyncState.Status.FAILED
    assert sync_state.last_failed_at is not None
    assert sync_state.retry_after > timezone.now()
    assert "musicbrainz rate limited" in sync_state.error_message


@pytest.mark.django_db
def test_sync_artist_releases_closes_owned_client(monkeypatch):
    class OwnedClient(FakeMusicBrainzClient):
        instances = []

        def __init__(self):
            super().__init__(release_groups=[], releases_by_group={})
            self.instances.append(self)

    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    monkeypatch.setattr("releasewatch.sync.MusicBrainzClient", OwnedClient)

    from releasewatch.sync import sync_artist_releases

    result = sync_artist_releases(artist=artist)

    assert result.event_ids == ()
    assert OwnedClient.instances[0].closed is True


@pytest.mark.django_db
def test_sync_artist_releases_skips_invalid_release_groups_and_undated_fallbacks():
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    group_mbid = uuid4()
    client = FakeMusicBrainzClient(
        release_groups=[
            release_group_payload("not-a-uuid"),
            release_group_payload(group_mbid, first_release_date=None),
        ],
        releases_by_group={str(group_mbid): [[]]},
    )

    from releasewatch.sync import sync_artist_releases

    result = sync_artist_releases(artist=artist, client=client)

    assert result.skipped_count == 1
    assert result.events_created == 0
    assert ReleaseGroup.objects.count() == 1
    assert ReleaseEvent.objects.count() == 0


@pytest.mark.django_db
def test_sync_artist_releases_records_non_rate_limit_failure_without_retry_time():
    class FailingClient(FakeMusicBrainzClient):
        def browse_release_groups(self, artist_mbid, *, limit=100, offset=0):
            raise RuntimeError("musicbrainz unavailable")

    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    client = FailingClient(release_groups=[], releases_by_group={})

    from releasewatch.sync import ReleaseSyncError, sync_artist_releases

    with pytest.raises(ReleaseSyncError):
        sync_artist_releases(artist=artist, client=client)

    sync_state = SyncState.objects.get(artist=artist, sync_type=SyncState.SyncType.RELEASES)
    assert sync_state.status == SyncState.Status.FAILED
    assert sync_state.retry_after is None
    assert sync_state.error_message == "musicbrainz unavailable"
