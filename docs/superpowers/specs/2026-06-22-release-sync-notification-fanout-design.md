# Release sync and notification fanout design

## Purpose

Build full MusicBrainz release sync for followed artists and create notification
rows for newly discovered release events.

This phase deepens the existing background workflow system. It uses the current
Celery queues, PostgreSQL models, MusicBrainz client, and notification models.
Email rendering and delivery stay out of scope.

## Sources checked

- MusicBrainz API: https://musicbrainz.org/doc/MusicBrainz_API
- MusicBrainz API search fields: https://musicbrainz.org/doc/MusicBrainz_API/Search
- Existing sync/import workflow design: `docs/superpowers/specs/2026-06-22-sync-import-workflows-design.md`
- Current domain models: `releasewatch/models.py`
- Current MusicBrainz client: `releasewatch/upstreams/musicbrainz.py`
- Current Celery tasks: `releasewatch/tasks.py`

## Approved decisions

- Implement full release sync now, not release-group-only sync.
- Use MusicBrainz as canonical release source.
- Sync followed artists where `Follow.is_ignored=False`.
- Store `ReleaseGroup`, concrete `Release`, and `ReleaseEvent` rows.
- Create notification rows during fanout, but do not send email yet.
- Keep Celery task arguments ID-only.
- Keep coverage floor at 97% or ratchet up if earned.
- Use TDD for each behavior.

## Non-goals

- No email rendering.
- No SMTP/provider delivery.
- No public UI for release lists or notification review.
- No RSS or iCal generation.
- No cover art sync.
- No MusicBrainz authenticated user data.
- No live network tests.
- No new broker or result backend.

## MusicBrainz behavior

The MusicBrainz API supports lookup, browse, and search requests. JSON output is
requested with `fmt=json`.

For this phase:

- Artist sync uses existing artist lookup behavior.
- Release-group sync uses existing release-group browse behavior.
- Concrete release sync adds release browsing by release group:
  - endpoint: `/ws/2/release`
  - browse key: `release-group=<release_group_mbid>`
  - params: `fmt=json`, `limit`, `offset`, `status`
  - include values: `media`, `release-groups`
- Default status filter is `official`.
- Release browse uses paging.
- Because MusicBrainz may return fewer releases than requested, offset advances
  by the number of releases returned, not by the requested limit.
- The default app-wide MusicBrainz throttle remains one request per second.

## Data model use

Existing models are sufficient for this phase.

`ReleaseGroup` stores:

- MusicBrainz release-group MBID
- owning `Artist`
- title
- primary type
- secondary types
- first release date and precision
- raw payload
- `last_refreshed_at`

`Release` stores:

- MusicBrainz release MBID
- owning `ReleaseGroup`
- country
- release date and precision
- status
- media format
- raw payload

`ReleaseEvent` stores notifiable release moments:

- release group
- optional concrete release
- country
- event date and precision
- visible/notifiable flags

`SyncState` stores status for artist release sync:

- sync type: `releases`
- status
- last started/succeeded/failed timestamps
- retry-after timestamp
- display-safe error message

`Notification` stores planned notification work:

- user
- release event
- cadence bucket
- status

## Service boundaries

Add `releasewatch/sync.py`.

Responsibilities:

- `sync_artist_releases(artist, client=None, release_status="official")`
- refresh artist metadata when needed
- browse release groups for the artist
- browse concrete releases for each release group
- upsert `ReleaseGroup`
- upsert `Release`
- upsert `ReleaseEvent`
- update `SyncState`
- return a sync result with counts
- close owned MusicBrainz clients

Add `releasewatch/notifications.py`.

Responsibilities:

- `fanout_release_event_notifications(release_event)`
- find active followers for the release event artist
- skip ignored follows
- skip users with no email preference row only by applying default daily behavior
- skip `email_enabled=False`
- skip cadence `off`
- compute cadence bucket
- upsert pending `Notification`
- return fanout result with counts

Extend `releasewatch/tasks.py`.

Responsibilities:

- `sync_artist_releases_task(artist_id)`
- `fanout_release_notifications(release_event_id)`
- `enqueue_due_artist_syncs(batch_size=100)`

Task routing:

- sync task goes to `sync`
- fanout task goes to `notifications`
- scanner task goes to `maintenance`

## Release event policy

Create one event per concrete release when a release has a MusicBrainz release
MBID.

Use release fields:

- country: release country or blank
- event date: release date
- date precision: release date precision
- release FK: concrete release

When a release group has no concrete releases but has a first release date,
create a fallback group-level event with no release FK.

Events are notifiable by default when they have an event date. Events without an
event date are visible but not notifiable.

Sync must be idempotent:

- running twice does not duplicate groups
- running twice does not duplicate releases
- running twice does not duplicate release events
- fanout running twice does not duplicate notifications

Existing unique constraints on release events and notifications are part of the
dedupe design.

## Notification policy

Fanout does not send email. It creates `Notification` rows only.

Follower selection:

- include `Follow.is_ignored=False`
- include users following the event's artist
- exclude users with `email_enabled=False`
- exclude users with cadence `off`

Preference default:

- if user has no `NotificationPreference`, treat cadence as daily with email
  enabled

Cadence buckets:

- instant: `instant:<release_event_id>`
- daily: `daily:<YYYY-MM-DD>` using current UTC date
- weekly: `weekly:<ISOYEAR>-W<ISOWEEK>` using current UTC week

Notification status:

- created rows start as `pending`
- existing rows are left unchanged

## Failure and retry policy

Transient upstream failures:

- mark `SyncState.status=failed`
- set `last_failed_at`
- store display-safe error summary
- set `retry_after` when upstream error carries retry metadata or a rate-limit
  reset is known
- allow Celery retry where task-level retry is safe

Permanent mapping failures:

- skip invalid individual release rows when possible
- record skipped count in result
- do not abort the whole artist sync unless all upstream work failed

Missing or malformed MBIDs:

- skip invalid row
- do not create partial rows with invalid UUID fields

Security:

- raw upstream payloads pass through existing redaction helpers
- task args are IDs only
- errors stored in `SyncState` are display-safe strings
- no provider tokens are involved in release sync

## Scanner policy

`enqueue_due_artist_syncs(batch_size=100)` chooses artists to sync from active
follows.

Due order:

- artists with no release sync state first
- failed states whose `retry_after` is null or due
- old successful states after a configurable freshness window

MVP freshness window:

- 24 hours for followed artists

Concurrency:

- scanner uses database locks where supported
- task handler rechecks due state before syncing
- repeated scans must not corrupt data

## Testing

Use TDD.

MusicBrainz client tests:

- release browse uses `/ws/2/release`
- request includes `release-group`, `status`, `limit`, `offset`, `fmt=json`,
  and `inc=media+release-groups`
- maps release MBID, country, date, date precision, status, media format, and
  raw payload
- rejects invalid pagination
- pages by returned count in service tests

Sync service tests:

- release groups are upserted
- releases are upserted
- release events are upserted
- no duplicates on repeated sync
- fallback group-level event created when no concrete releases exist
- undated events are visible but not notifiable
- invalid MBID rows are skipped
- sync state records success
- sync state records failure and retry time
- owned MusicBrainz client closes

Notification fanout tests:

- daily notification rows created for followers
- weekly and instant buckets are computed correctly
- cadence off creates no rows
- email disabled creates no rows
- ignored follows create no rows
- duplicate fanout does not duplicate notifications
- missing preference defaults to daily

Task tests:

- sync task accepts only artist ID
- fanout task accepts only release event ID
- scanner enqueues due artists in bounded batches
- scanner skips artists not due
- routing sends tasks to `sync`, `notifications`, and `maintenance`

Verification:

- focused pytest for each task
- `uv run coverage report` must pass at 97% or higher
- `uv run ruff check .`
- `uv run bandit -c pyproject.toml -r config releasewatch`
- `uv run python manage.py check`
- Podman Compose config still renders
- Celery app report still loads

## Implementation split

One implementation plan is acceptable for this phase.

Task groups:

1. Extend MusicBrainz release client.
2. Add release sync services.
3. Add notification fanout services.
4. Add Celery task wrappers and routes.
5. Add scanner behavior.
6. Update docs and handoff.
7. Run full verification and checkpoint tag.

