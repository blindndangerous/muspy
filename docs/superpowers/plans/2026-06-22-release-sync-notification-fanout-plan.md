# Release Sync and Notification Fanout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sync concrete MusicBrainz releases for followed artists and create deduped notification rows for newly discovered release events.

**Architecture:** Extend the existing MusicBrainz client with release browsing, add focused sync and notification services, then expose them through existing Celery workers. PostgreSQL remains the durable workflow store, RabbitMQ routes tasks, and task arguments stay ID-only.

**Tech Stack:** Python 3.14, Django 6, Celery 5.6, RabbitMQ, PostgreSQL 18, MusicBrainz WS/2 JSON API, `uv`, pytest.

---

## File Structure

- Modify `releasewatch/upstreams/musicbrainz.py`: add concrete release browse and mapping.
- Modify `tests/test_musicbrainz_client.py`: cover release browse request shape, mapping, and validation.
- Create `releasewatch/sync.py`: release sync service, sync result dataclass, sync state helpers, MusicBrainz paging.
- Create `tests/test_release_sync.py`: sync service TDD coverage.
- Create `releasewatch/notifications.py`: notification fanout service and cadence bucket helpers.
- Create `tests/test_notifications.py`: fanout TDD coverage.
- Modify `releasewatch/tasks.py`: add release sync task, notification fanout task, due artist scanner.
- Modify `config/settings.py`: add Celery routes for new tasks and freshness setting.
- Modify `tests/test_task_config.py`: assert new routes.
- Create or modify `tests/test_release_sync_tasks.py`: task and scanner coverage.
- Modify `docs/development.md`, `docs/security.md`, `docs/agent-handoff.md`: record operations and checkpoint.

Use `C:\Users\blind\.local\bin\uv.exe` for every `uv` command in this Windows workspace.

For DB-backed tests, use SQLite unless a task explicitly says otherwise:

```powershell
$env:SECRET_KEY='release-sync-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-release-sync.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
```

Cleanup after each DB-backed command:

```powershell
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-release-sync.sqlite3* -ErrorAction SilentlyContinue
```

---

## Task 1: Extend MusicBrainz Release Client

**Files:**

- Modify: `releasewatch/upstreams/musicbrainz.py`
- Modify: `tests/test_musicbrainz_client.py`

- [ ] **Step 1: Write failing release browse tests**

Append to `tests/test_musicbrainz_client.py`:

```python
RELEASE_MBID = "b84ee12a-6b0e-4c20-8d79-8305a5d51b5a"


def test_browse_releases_by_release_group_requests_release_endpoint_with_filters():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "releases": [
                    {
                        "id": RELEASE_MBID,
                        "country": "US",
                        "date": "1990-04-19",
                        "status": "Official",
                        "media": [{"format": "CD"}],
                    }
                ]
            },
        )

    client = MusicBrainzClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        throttle=_instant_throttle(),
    )

    releases = client.browse_releases_by_release_group(
        RELEASE_GROUP_MBID,
        status="official",
        limit=25,
        offset=50,
    )

    assert seen == {
        "path": "/ws/2/release",
        "params": {
            "release-group": RELEASE_GROUP_MBID,
            "status": "official",
            "limit": "25",
            "offset": "50",
            "inc": "media+release-groups",
            "fmt": "json",
        },
    }
    assert releases[0].mbid == RELEASE_MBID


def test_browse_releases_by_release_group_maps_release_payload():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "releases": [
                    {
                        "id": RELEASE_MBID,
                        "country": "GB",
                        "date": "1990-04",
                        "status": "Official",
                        "media": [{"format": "Vinyl"}, {"format": "Digital Media"}],
                        "release-group": {"id": RELEASE_GROUP_MBID},
                    }
                ]
            },
        )

    client = MusicBrainzClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        throttle=_instant_throttle(),
    )

    release = client.browse_releases_by_release_group(RELEASE_GROUP_MBID)[0]

    assert release.country == "GB"
    assert release.release_date == date(1990, 4, 1)
    assert release.release_date_precision == DatePrecision.MONTH
    assert release.status == "Official"
    assert release.media_format == "Vinyl, Digital Media"
    assert release.raw_payload["release-group"] == {"id": RELEASE_GROUP_MBID}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_browse_releases_by_release_group_rejects_invalid_limit_and_offset(kwargs):
    client = MusicBrainzClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
        ),
        throttle=_instant_throttle(),
    )

    with pytest.raises(ValueError):
        client.browse_releases_by_release_group(RELEASE_GROUP_MBID, **kwargs)
```

- [ ] **Step 2: Run red tests**

```powershell
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_musicbrainz_client.py::test_browse_releases_by_release_group_requests_release_endpoint_with_filters tests/test_musicbrainz_client.py::test_browse_releases_by_release_group_maps_release_payload tests/test_musicbrainz_client.py::test_browse_releases_by_release_group_rejects_invalid_limit_and_offset -q
```

Expected: fails because `browse_releases_by_release_group` is missing.

- [ ] **Step 3: Implement release browse**

Modify imports in `releasewatch/upstreams/musicbrainz.py`:

```python
from releasewatch.upstreams.base import (
    FixedIntervalThrottle,
    LockedThrottle,
    UpstreamArtist,
    UpstreamArtistAlias,
    UpstreamClient,
    UpstreamRelease,
    UpstreamReleaseGroup,
    parse_partial_date,
)
```

Add method to `MusicBrainzClient`:

```python
    def browse_releases_by_release_group(
        self,
        release_group_mbid: str,
        *,
        status: str = "official",
        limit: int = 100,
        offset: int = 0,
    ) -> list[UpstreamRelease]:
        _validate_pagination(limit=limit, offset=offset)
        payload = self.get_json(
            "/release",
            params={
                "release-group": release_group_mbid,
                "status": status,
                "limit": limit,
                "offset": offset,
                "inc": "media+release-groups",
                "fmt": "json",
            },
        )
        return [_release_from_payload(release) for release in payload.get("releases", [])]
```

Add helpers:

```python
def _release_from_payload(payload: dict[str, Any]) -> UpstreamRelease:
    release_date, release_date_precision = parse_partial_date(payload.get("date", ""))
    return UpstreamRelease(
        mbid=payload.get("id", ""),
        country=payload.get("country", ""),
        release_date=release_date,
        release_date_precision=release_date_precision,
        status=payload.get("status", ""),
        media_format=_media_format_from_payload(payload),
        raw_payload=deepcopy(payload),
    )


def _media_format_from_payload(payload: dict[str, Any]) -> str:
    formats = [
        medium.get("format", "")
        for medium in payload.get("media", [])
        if medium.get("format", "")
    ]
    return ", ".join(dict.fromkeys(formats))
```

- [ ] **Step 4: Run green tests**

```powershell
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_musicbrainz_client.py -q
C:\Users\blind\.local\bin\uv.exe run ruff check releasewatch/upstreams/musicbrainz.py tests/test_musicbrainz_client.py
```

Expected: MusicBrainz tests pass, Ruff passes.

- [ ] **Step 5: Commit checkpoint**

```powershell
git add releasewatch/upstreams/musicbrainz.py tests/test_musicbrainz_client.py
git commit -m "feat: add musicbrainz release browse"
```

---

## Task 2: Add Release Sync Service

**Files:**

- Create: `releasewatch/sync.py`
- Create: `tests/test_release_sync.py`

- [ ] **Step 1: Write failing sync service tests**

Create `tests/test_release_sync.py`:

```python
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
from releasewatch.upstreams import UpstreamRelease, UpstreamReleaseGroup
from releasewatch.upstreams.base import UpstreamRateLimited


@dataclass
class FakeMusicBrainzClient:
    release_groups: list[UpstreamReleaseGroup]
    releases_by_group: dict[str, list[list[UpstreamRelease]]]
    closed: bool = False

    def lookup_artist(self, mbid):
        raise AssertionError("lookup_artist is not part of these tests")

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
        index = offset
        if index >= len(pages):
            return []
        return pages[index]

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
```

- [ ] **Step 2: Run red tests**

```powershell
$env:SECRET_KEY='release-sync-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-release-sync.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_release_sync.py -q
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-release-sync.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: fails because `releasewatch.sync` is missing.

- [ ] **Step 3: Implement sync service**

Create `releasewatch/sync.py`:

```python
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
        group, created = _upsert_release_group(artist=artist, mbid=group_mbid, upstream=upstream_group)
        counts["release_groups_created" if created else "release_groups_updated"] += 1
        releases = _browse_all_releases(
            client=client,
            release_group_mbid=str(group_mbid),
            release_status=release_status,
        )
        if not releases:
            event, event_created = _upsert_group_event(group=group, upstream_group=upstream_group)
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
```

- [ ] **Step 4: Run green tests**

```powershell
$env:SECRET_KEY='release-sync-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-release-sync.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_release_sync.py -q
C:\Users\blind\.local\bin\uv.exe run ruff check releasewatch/sync.py tests/test_release_sync.py
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-release-sync.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: sync tests pass, Ruff passes.

- [ ] **Step 5: Commit checkpoint**

```powershell
git add releasewatch/sync.py tests/test_release_sync.py
git commit -m "feat: add release sync service"
```

---

## Task 3: Add Notification Fanout Service

**Files:**

- Create: `releasewatch/notifications.py`
- Create: `tests/test_notifications.py`

- [ ] **Step 1: Write failing notification tests**

Create `tests/test_notifications.py`:

```python
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
```

- [ ] **Step 2: Run red tests**

```powershell
$env:SECRET_KEY='release-sync-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-release-sync.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_notifications.py -q
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-release-sync.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: fails because `releasewatch.notifications` is missing.

- [ ] **Step 3: Implement notification service**

Create `releasewatch/notifications.py`:

```python
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from releasewatch.models import (
    Follow,
    Notification,
    NotificationCadence,
    NotificationPreference,
    ReleaseEvent,
)


@dataclass(frozen=True)
class NotificationFanoutResult:
    release_event: ReleaseEvent
    created_count: int = 0
    existing_count: int = 0
    skipped_count: int = 0


def fanout_release_event_notifications(
    *,
    release_event: ReleaseEvent,
    now: datetime | None = None,
) -> NotificationFanoutResult:
    now = now or timezone.now()
    created_count = 0
    existing_count = 0
    skipped_count = 0
    follows = (
        Follow.objects.select_related("user")
        .filter(artist=release_event.release_group.artist)
        .order_by("user_id")
    )
    for follow in follows:
        if follow.is_ignored or not release_event.notifiable:
            skipped_count += 1
            continue
        preference = _preference_for_user(follow.user)
        if not preference.email_enabled or preference.cadence == NotificationCadence.OFF:
            skipped_count += 1
            continue
        bucket = _cadence_bucket(
            cadence=preference.cadence,
            release_event=release_event,
            now=now,
        )
        _, created = Notification.objects.get_or_create(
            user=follow.user,
            release_event=release_event,
            cadence_bucket=bucket,
            defaults={"status": Notification.Status.PENDING},
        )
        if created:
            created_count += 1
        else:
            existing_count += 1
    return NotificationFanoutResult(
        release_event=release_event,
        created_count=created_count,
        existing_count=existing_count,
        skipped_count=skipped_count,
    )


def _preference_for_user(user):
    preference = getattr(user, "notificationpreference", None)
    if preference is None:
        return _DefaultPreference()
    return preference


@dataclass(frozen=True)
class _DefaultPreference:
    cadence: str = NotificationCadence.DAILY
    email_enabled: bool = True


def _cadence_bucket(*, cadence: str, release_event: ReleaseEvent, now: datetime) -> str:
    if cadence == NotificationCadence.INSTANT:
        return f"instant:{release_event.id}"
    if cadence == NotificationCadence.WEEKLY:
        iso_year, iso_week, _ = now.isocalendar()
        return f"weekly:{iso_year}-W{iso_week:02d}"
    return f"daily:{now.date().isoformat()}"
```

- [ ] **Step 4: Run green tests**

```powershell
$env:SECRET_KEY='release-sync-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-release-sync.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_notifications.py -q
C:\Users\blind\.local\bin\uv.exe run ruff check releasewatch/notifications.py tests/test_notifications.py
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-release-sync.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: notification tests pass, Ruff passes.

- [ ] **Step 5: Commit checkpoint**

```powershell
git add releasewatch/notifications.py tests/test_notifications.py
git commit -m "feat: add notification fanout service"
```

---

## Task 4: Add Release Sync Celery Tasks, Routes, and Scanner

**Files:**

- Modify: `releasewatch/tasks.py`
- Modify: `config/settings.py`
- Modify: `tests/test_task_config.py`
- Create: `tests/test_release_sync_tasks.py`

- [ ] **Step 1: Write failing route and task tests**

Append to `tests/test_task_config.py`:

```python
def test_celery_routes_release_sync_tasks_to_expected_queues():
    routes = app.conf.task_routes

    assert routes["releasewatch.tasks.sync_artist_releases_task"]["queue"] == "sync"
    assert routes["releasewatch.tasks.fanout_release_notifications"]["queue"] == "notifications"
    assert routes["releasewatch.tasks.enqueue_due_artist_syncs"]["queue"] == "maintenance"
```

Create `tests/test_release_sync_tasks.py`:

```python
from uuid import uuid4

import pytest
from django.utils import timezone

from releasewatch.models import Artist, Follow, ReleaseEvent, ReleaseGroup, SyncState


def create_user(username):
    from django.contrib.auth import get_user_model

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
```

- [ ] **Step 2: Run red tests**

```powershell
$env:SECRET_KEY='release-sync-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-release-sync.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_task_config.py::test_celery_routes_release_sync_tasks_to_expected_queues tests/test_release_sync_tasks.py -q
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-release-sync.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: missing routes and tasks fail.

- [ ] **Step 3: Add settings routes and freshness setting**

In `config/settings.py`, extend `CELERY_TASK_ROUTES`:

```python
    "releasewatch.tasks.sync_artist_releases_task": {"queue": "sync"},
    "releasewatch.tasks.fanout_release_notifications": {"queue": "notifications"},
    "releasewatch.tasks.enqueue_due_artist_syncs": {"queue": "maintenance"},
```

Add:

```python
RELEASE_SYNC_FRESHNESS_HOURS = _env_int(
    "RELEASE_SYNC_FRESHNESS_HOURS",
    default=24,
    minimum=1,
    maximum=720,
)
```

- [ ] **Step 4: Implement task wrappers and scanner**

Modify imports in `releasewatch/tasks.py`:

```python
from django.conf import settings
from django.db.models import F, Q

from releasewatch.notifications import fanout_release_event_notifications
from releasewatch.sync import ReleaseSyncError, sync_artist_releases
```

Add tasks after existing import tasks:

```python
@shared_task(
    bind=True,
    autoretry_for=(ReleaseSyncError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
)
def sync_artist_releases_task(self, artist_id: int) -> None:
    artist = Artist.objects.get(pk=artist_id)
    if not _artist_release_sync_due(artist):
        return
    result = sync_artist_releases(artist=artist)
    for event_id in result.event_ids:
        fanout_release_notifications.delay(event_id)


@shared_task(bind=True, autoretry_for=(TimeoutError,), retry_backoff=True, retry_jitter=True)
def fanout_release_notifications(self, release_event_id: int) -> None:
    event = ReleaseEvent.objects.select_related("release_group__artist").get(pk=release_event_id)
    fanout_release_event_notifications(release_event=event)


@shared_task
def enqueue_due_artist_syncs(batch_size: int = 100) -> int:
    artist_ids = _due_artist_ids(batch_size=batch_size)
    for artist_id in artist_ids:
        sync_artist_releases_task.delay(artist_id)
    return len(artist_ids)
```

Add helpers:

```python
def _due_artist_ids(*, batch_size: int) -> list[int]:
    now = timezone.now()
    stale_before = now - timezone.timedelta(hours=settings.RELEASE_SYNC_FRESHNESS_HOURS)
    followed_artists = Artist.objects.filter(follow__is_ignored=False).distinct()
    release_sync_states = SyncState.objects.filter(
        artist_id=OuterRef("pk"),
        sync_type=SyncState.SyncType.RELEASES,
    )

    never_synced = (
        followed_artists.annotate(has_release_sync=Exists(release_sync_states))
        .filter(has_release_sync=False)
        .order_by("id")
        .values_list("id", flat=True)
    )
    retryable_failures = (
        followed_artists.filter(
            sync_states__sync_type=SyncState.SyncType.RELEASES,
            sync_states__status=SyncState.Status.FAILED,
        )
        .filter(Q(sync_states__retry_after__isnull=True) | Q(sync_states__retry_after__lte=now))
        .order_by("sync_states__retry_after", "id")
        .values_list("id", flat=True)
    )
    stale_successes = (
        followed_artists.filter(
            sync_states__sync_type=SyncState.SyncType.RELEASES,
            sync_states__status=SyncState.Status.SUCCEEDED,
        )
        .filter(
            Q(sync_states__last_succeeded_at__isnull=True)
            | Q(sync_states__last_succeeded_at__lt=stale_before)
        )
        .order_by("sync_states__last_succeeded_at", "id")
        .values_list("id", flat=True)
    )
    return _take_unique_ids(
        never_synced,
        retryable_failures,
        stale_successes,
        batch_size=batch_size,
    )


def _take_unique_ids(*querysets, batch_size: int) -> list[int]:
    due_ids: list[int] = []
    seen_ids: set[int] = set()
    for queryset in querysets:
        for artist_id in queryset:
            if artist_id in seen_ids:
                continue
            due_ids.append(artist_id)
            seen_ids.add(artist_id)
            if len(due_ids) >= batch_size:
                return due_ids
    return due_ids


def _artist_release_sync_due(
    artist: Artist,
    *,
    now=None,
    stale_before=None,
) -> bool:
    now = now or timezone.now()
    stale_before = stale_before or now - timezone.timedelta(
        hours=settings.RELEASE_SYNC_FRESHNESS_HOURS
    )
    sync_state = SyncState.objects.filter(
        artist=artist,
        sync_type=SyncState.SyncType.RELEASES,
    ).first()
    if sync_state is None:
        return True
    if sync_state.status == SyncState.Status.FAILED:
        return sync_state.retry_after is None or sync_state.retry_after <= now
    if sync_state.last_succeeded_at is None:
        return True
    return sync_state.last_succeeded_at < stale_before


```

Also add imports for `Q`, `Exists`, and `OuterRef` from `django.db.models`, plus `Artist`, `ReleaseEvent`, and `SyncState` from `releasewatch.models`.

- [ ] **Step 5: Run green tests**

```powershell
$env:SECRET_KEY='release-sync-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-release-sync.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_task_config.py tests/test_release_sync_tasks.py -q
C:\Users\blind\.local\bin\uv.exe run ruff check config/settings.py releasewatch/tasks.py tests/test_task_config.py tests/test_release_sync_tasks.py
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-release-sync.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: task config and task tests pass, Ruff passes.

- [ ] **Step 6: Commit checkpoint**

```powershell
git add config/settings.py releasewatch/tasks.py tests/test_task_config.py tests/test_release_sync_tasks.py
git commit -m "feat: add release sync celery tasks"
```

---

## Task 5: Docs, Full Verification, and Checkpoint

**Files:**

- Modify: `docs/development.md`
- Modify: `docs/security.md`
- Modify: `docs/agent-handoff.md`
- Possibly modify: `pyproject.toml`
- Possibly modify: `tests/test_quality_config.py`

- [ ] **Step 1: Update user-facing docs**

In `docs/development.md`, add under "Background workers":

```markdown
Run a release sync worker on bare metal:

```sh
uv run celery -A config worker -Q sync --loglevel=info
```

Run a notification fanout worker on bare metal:

```sh
uv run celery -A config worker -Q notifications --loglevel=info
```
```

In `docs/security.md`, add:

```markdown
Release sync stores raw MusicBrainz payloads after normal payload redaction.
Celery task arguments for sync and fanout must use database IDs only.
```

- [ ] **Step 2: Run focused full feature tests**

```powershell
$env:SECRET_KEY='release-sync-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-release-sync.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_musicbrainz_client.py tests/test_release_sync.py tests/test_notifications.py tests/test_release_sync_tasks.py tests/test_task_config.py -q
C:\Users\blind\.local\bin\uv.exe run ruff check releasewatch/upstreams/musicbrainz.py releasewatch/sync.py releasewatch/notifications.py releasewatch/tasks.py tests/test_musicbrainz_client.py tests/test_release_sync.py tests/test_notifications.py tests/test_release_sync_tasks.py tests/test_task_config.py
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-release-sync.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: all focused tests pass and Ruff passes.

- [ ] **Step 3: Run full coverage split**

```powershell
Remove-Item Env:DEBUG,Env:DATABASE_URL,Env:PROVIDER_TOKEN_ENCRYPTION_KEY -ErrorAction SilentlyContinue
$env:SECRET_KEY='release-sync-test-secret'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run coverage erase
C:\Users\blind\.local\bin\uv.exe run coverage run -m pytest tests/test_settings_security.py tests/test_quality_config.py tests/test_task_config.py tests/test_upstream_base.py tests/test_musicbrainz_client.py tests/test_listenbrainz_client.py tests/test_lastfm_client.py -q
if ($LASTEXITCODE -ne 0) { Remove-Item Env:SECRET_KEY,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue; exit $LASTEXITCODE }
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-release-sync.sqlite3'
C:\Users\blind\.local\bin\uv.exe run coverage run --append -m pytest tests/test_provider_accounts.py tests/test_import_workflows.py tests/test_release_sync.py tests/test_notifications.py tests/test_release_sync_tasks.py -q
if ($LASTEXITCODE -ne 0) { Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue; Remove-Item .tmp-release-sync.sqlite3* -ErrorAction SilentlyContinue; exit $LASTEXITCODE }
C:\Users\blind\.local\bin\uv.exe run coverage run --append -m pytest tests/test_domain_models.py tests/test_dev_admin_command.py tests/test_project_smoke.py tests/test_container_files.py tests/test_ci_workflow.py -q
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-release-sync.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: all test groups pass.

- [ ] **Step 4: Run quality and security checks**

```powershell
C:\Users\blind\.local\bin\uv.exe run coverage report
C:\Users\blind\.local\bin\uv.exe run ruff check .
C:\Users\blind\.local\bin\uv.exe run bandit -c pyproject.toml -r config releasewatch
$env:SECRET_KEY='release-sync-test-secret'
$env:DEBUG='1'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run python manage.py check
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
exit $exit
```

Expected:

- coverage is at least 97%
- Ruff passes
- Bandit reports no issues
- Django check reports no issues

If coverage rises above 97%, update `pyproject.toml` and `tests/test_quality_config.py` to the new floor and rerun `coverage report` plus `tests/test_quality_config.py::test_coverage_floor_is_ratcheted_to_current_level`.

- [ ] **Step 5: Run Podman verification**

```powershell
$composeDir='C:\Users\blind\AppData\Local\Microsoft\WinGet\Packages\Docker.DockerCompose_Microsoft.Winget.Source_8wekyb3d8bbwe'
$env:Path="$composeDir;$env:Path"
podman build -f Containerfile -t muspy:dev .
podman compose -f compose.yml config
podman compose -f compose.yml up -d db broker redis
podman compose -f compose.yml run --rm web python manage.py check
podman compose -f compose.yml run --rm worker-sync celery -A config report
podman compose -f compose.yml run --rm worker-notifications celery -A config report
podman compose -f compose.yml down -v
```

Expected: image builds, compose config renders, services become healthy, Django check passes, sync worker can load Celery app, notification worker can load Celery app, cleanup succeeds.

- [ ] **Step 6: Update agent handoff**

In `docs/agent-handoff.md`:

- current phase: release sync and notification fanout complete
- last known good commits: include each commit from this plan
- next required step: email rendering/delivery plan or release UI plan
- verification notes: exact command results from this task

- [ ] **Step 7: Commit final checkpoint and tag**

```powershell
git add docs/development.md docs/security.md docs/agent-handoff.md pyproject.toml tests/test_quality_config.py
git commit -m "docs: record release sync fanout checkpoint"
git tag -f checkpoint/release-sync-notification-fanout
git status --short --branch --untracked-files=all
```

Expected: worktree clean and tag points to final checkpoint.
