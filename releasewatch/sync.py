from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from releasewatch.models import Artist, Release, ReleaseEvent, ReleaseGroup, SyncState
from releasewatch.upstreams import MusicBrainzClient, UpstreamRateLimited
from releasewatch.upstreams.base import UpstreamRelease, UpstreamReleaseGroup


class ReleaseSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseSyncResult:
    artist: Artist
    release_groups_created: int = 0
    release_groups_updated: int = 0
    releases_created: int = 0
    releases_updated: int = 0
    events_created: int = 0
    events_updated: int = 0
    skipped_count: int = 0
    event_ids: tuple[int, ...] = ()


def sync_artist_releases(
    *,
    artist: Artist,
    client: MusicBrainzClient | None = None,
    release_status: str = "official",
) -> ReleaseSyncResult:
    owns_client = client is None
    client = client or MusicBrainzClient()
    sync_state = _mark_sync_started(artist)
    try:
        result = _sync_artist_releases(
            artist=artist,
            client=client,
            release_status=release_status,
        )
    except Exception as error:
        _mark_sync_failed(sync_state=sync_state, error=error)
        raise ReleaseSyncError(str(error)) from error
    finally:
        if owns_client:
            client.close()
    _mark_sync_succeeded(sync_state)
    return result


def _sync_artist_releases(
    *,
    artist: Artist,
    client: MusicBrainzClient,
    release_status: str,
) -> ReleaseSyncResult:
    counts = {
        "release_groups_created": 0,
        "release_groups_updated": 0,
        "releases_created": 0,
        "releases_updated": 0,
        "events_created": 0,
        "events_updated": 0,
        "skipped_count": 0,
    }
    event_ids: list[int] = []
    release_groups = client.browse_release_groups(str(artist.mbid), limit=100, offset=0)
    for upstream_group in release_groups:
        group_mbid = _valid_uuid(upstream_group.mbid)
        if group_mbid is None:
            counts["skipped_count"] += 1
            continue
        group, created = _upsert_release_group(
            artist=artist,
            mbid=group_mbid,
            upstream=upstream_group,
        )
        counts["release_groups_created" if created else "release_groups_updated"] += 1
        releases = _browse_all_releases(
            client=client,
            release_group_mbid=str(group_mbid),
            release_status=release_status,
        )
        if not releases:
            event, event_created = _upsert_group_event(
                group=group,
                upstream_group=upstream_group,
            )
            if event is not None:
                counts["events_created" if event_created else "events_updated"] += 1
                event_ids.append(event.id)
            continue
        for upstream_release in releases:
            release_mbid = _valid_uuid(upstream_release.mbid)
            if release_mbid is None:
                counts["skipped_count"] += 1
                continue
            release, release_created = _upsert_release(
                group=group,
                mbid=release_mbid,
                upstream=upstream_release,
            )
            counts["releases_created" if release_created else "releases_updated"] += 1
            event, event_created = _upsert_release_event(group=group, release=release)
            counts["events_created" if event_created else "events_updated"] += 1
            event_ids.append(event.id)
    return ReleaseSyncResult(artist=artist, event_ids=tuple(event_ids), **counts)


def _browse_all_releases(
    *,
    client: MusicBrainzClient,
    release_group_mbid: str,
    release_status: str,
) -> list[UpstreamRelease]:
    releases: list[UpstreamRelease] = []
    offset = 0
    while True:
        page = client.browse_releases_by_release_group(
            release_group_mbid,
            status=release_status,
            limit=100,
            offset=offset,
        )
        if not page:
            return releases
        releases.extend(page)
        offset += len(page)


def _upsert_release_group(
    *,
    artist: Artist,
    mbid: UUID,
    upstream: UpstreamReleaseGroup,
) -> tuple[ReleaseGroup, bool]:
    return ReleaseGroup.objects.update_or_create(
        mbid=mbid,
        defaults={
            "artist": artist,
            "title": upstream.title[:255],
            "primary_type": upstream.primary_type[:64],
            "secondary_types": upstream.secondary_types,
            "first_release_date": upstream.first_release_date,
            "first_release_precision": upstream.first_release_precision,
            "raw_payload": upstream.raw_payload,
            "last_refreshed_at": timezone.now(),
        },
    )


def _upsert_release(
    *,
    group: ReleaseGroup,
    mbid: UUID,
    upstream: UpstreamRelease,
) -> tuple[Release, bool]:
    return Release.objects.update_or_create(
        mbid=mbid,
        defaults={
            "release_group": group,
            "country": upstream.country[:2],
            "release_date": upstream.release_date,
            "release_date_precision": upstream.release_date_precision,
            "status": upstream.status[:64],
            "media_format": upstream.media_format[:64],
            "raw_payload": upstream.raw_payload,
        },
    )


def _upsert_release_event(
    *,
    group: ReleaseGroup,
    release: Release,
) -> tuple[ReleaseEvent, bool]:
    return ReleaseEvent.objects.update_or_create(
        release_group=group,
        release=release,
        country=release.country,
        defaults={
            "event_date": release.release_date,
            "date_precision": release.release_date_precision,
            "visible": True,
            "notifiable": release.release_date is not None,
        },
    )


def _upsert_group_event(
    *,
    group: ReleaseGroup,
    upstream_group: UpstreamReleaseGroup,
) -> tuple[ReleaseEvent, bool] | tuple[None, bool]:
    if upstream_group.first_release_date is None:
        return None, False

    event, created = ReleaseEvent.objects.update_or_create(
        release_group=group,
        release=None,
        country="",
        defaults={
            "event_date": upstream_group.first_release_date,
            "date_precision": upstream_group.first_release_precision,
            "visible": True,
            "notifiable": True,
        },
    )
    return event, created


def _mark_sync_started(artist: Artist) -> SyncState:
    with transaction.atomic():
        sync_state, _ = SyncState.objects.select_for_update().update_or_create(
            artist=artist,
            sync_type=SyncState.SyncType.RELEASES,
            defaults={
                "status": SyncState.Status.STARTED,
                "last_started_at": timezone.now(),
                "error_message": "",
                "retry_after": None,
            },
        )
    return sync_state


def _mark_sync_succeeded(sync_state: SyncState) -> None:
    sync_state.status = SyncState.Status.SUCCEEDED
    sync_state.last_succeeded_at = timezone.now()
    sync_state.error_message = ""
    sync_state.retry_after = None
    sync_state.save(
        update_fields=[
            "status",
            "last_succeeded_at",
            "error_message",
            "retry_after",
            "updated_at",
        ]
    )


def _mark_sync_failed(*, sync_state: SyncState, error: Exception) -> None:
    sync_state.status = SyncState.Status.FAILED
    sync_state.last_failed_at = timezone.now()
    sync_state.error_message = str(error)
    sync_state.retry_after = _retry_after_for_error(error)
    sync_state.save(
        update_fields=[
            "status",
            "last_failed_at",
            "error_message",
            "retry_after",
            "updated_at",
        ]
    )


def _retry_after_for_error(error: Exception):
    if isinstance(error, UpstreamRateLimited):
        return timezone.now() + timedelta(hours=1)
    return None


def _valid_uuid(value: str):
    try:
        return UUID(str(value))
    except ValueError:
        return None
