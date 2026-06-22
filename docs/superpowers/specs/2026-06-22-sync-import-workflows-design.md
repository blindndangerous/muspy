# Sync and import workflows design

## Purpose

Build production-grade background workflow foundations for imports, MusicBrainz sync, and notification fanout.

This phase adds the infrastructure and service boundaries needed for large batches of users and artists. It should still run locally in Compose and bare metal, but the design must not assume one process or one small queue.

## Sources checked

- Celery Django integration: https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html
- Celery broker guidance: https://docs.celeryq.dev/en/stable/getting-started/first-steps-with-celery.html
- Celery Redis broker notes: https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html
- django-celery-beat setup: https://github.com/celery/django-celery-beat
- Django 6 Tasks reference: https://docs.djangoproject.com/en/6.0/ref/tasks/
- Existing upstream client spec: `docs/superpowers/specs/2026-06-21-upstream-clients-design.md`
- Existing domain model plan and implementation: `releasewatch.models`

## Approved decisions

- Use Celery for production task execution now.
- Use RabbitMQ as the Celery broker.
- Use Redis only where it has a clear job: cache, shared provider rate gates, or short locks.
- Use Postgres as the durable source of truth for workflow state.
- Do not use a Celery result backend in this phase.
- Add dedicated worker services from the start.
- Add provider account foundation now, including encrypted token storage for providers that need recurring imports.
- Keep all task payloads ID-only.
- Store enough sync summary data now for later UI, even before building the UI.

## Non-goals

- No public import UI in this phase.
- No notification email rendering or sending in this phase.
- No RSS or iCal feed generation in this phase.
- No OAuth flow.
- No live provider tests.
- No Celery result backend.
- No Kubernetes manifests.

## Runtime architecture

Services:

- `web`: Django app.
- `db`: PostgreSQL 18.
- `broker`: RabbitMQ.
- `redis`: Redis for cache/rate-limit/short-lock use.
- `worker-imports`: Celery worker consuming the `imports` queue.
- `worker-sync`: Celery worker consuming the `sync` queue.
- `worker-notifications`: Celery worker consuming the `notifications` queue.
- `worker-maintenance`: Celery worker consuming the `maintenance` queue.
- `beat`: Celery beat with django-celery-beat database scheduler.

RabbitMQ routes work. Redis does not become the broker. Postgres stores all durable user-visible state. If broker messages are lost or duplicated, periodic scanner tasks can find due rows in Postgres and enqueue them again.

Dedicated workers are required from the start so one slow workload cannot block unrelated work. A small deployment can still run lower concurrency, but configuration and Compose must model separate queues now.

## Celery configuration

Add `config/celery.py` using the documented Django/Celery pattern:

- set `DJANGO_SETTINGS_MODULE`
- create Celery app named `config`
- load settings via `namespace="CELERY"`
- autodiscover tasks

Settings:

- `CELERY_BROKER_URL` from env, defaulting to local RabbitMQ.
- `CELERY_TASK_DEFAULT_QUEUE = "maintenance"`.
- queue routes:
  - import tasks to `imports`
  - sync tasks to `sync`
  - notification tasks to `notifications`
  - maintenance/scanner tasks to `maintenance`
- JSON serializers only.
- UTC timezone.
- retry/backoff defaults for transient failures.
- no configured result backend.
- `CELERY_TASK_IGNORE_RESULT = True`.
- `CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"`.

Tests may use eager execution for task wrapper tests, but domain service tests should call services directly.

## Provider accounts

Add `ProviderAccount` for recurring imports and future account linking.

Fields:

- `user`
- `provider`: `lastfm`, `listenbrainz`
- `external_username`
- `token_encrypted`, blank allowed
- `scopes`, JSON list
- `status`: `active`, `revoked`, `failed`
- `last_imported_at`
- `last_error_message`
- `created_at`
- `updated_at`

Constraints:

- unique active account per user/provider/external username
- indexes for provider/status and user/provider

Token policy:

- Last.fm stores username only in this phase.
- ListenBrainz may store an encrypted token if the user chooses recurring import.
- One-shot imports can pass a token to the service and must not persist it.
- Tokens must never appear in task args, logs, admin search fields, raw error strings, or unredacted payloads.
- Encryption key comes from env and is distinct from `SECRET_KEY`.
- If token storage is enabled and the encryption key is missing, fail fast.

## Import workflow

Supported sources:

- Last.fm user top artists.
- ListenBrainz user artists.
- Plain text artist names.

Workflow:

1. Caller creates `ImportRun`.
2. Caller enqueues import task with `ImportRun.id` or `ProviderAccount.id`.
3. Import worker fetches provider data in bounded pages.
4. Service maps provider rows to `ImportedArtist`.
5. Service creates or updates `ImportCandidate` rows in chunks.
6. Service links a candidate to canonical `Artist` when confident.
7. User review later accepts, ignores, or rejects candidates.

Matching policy:

- If upstream row includes MBID, look up or create `Artist` from MusicBrainz.
- If upstream row lacks MBID, search MusicBrainz by artist name.
- If one high-confidence match exists, link it.
- If no clear match exists, leave candidate pending.
- Never create duplicate candidate rows for the same import/source identifier.
- Re-running the same import task must not duplicate candidates.

Review policy:

- Accepted candidate creates `Follow`.
- Ignored or rejected candidate is not suggested again for that import.
- Existing `Follow.is_ignored=True` prevents re-following ignored artists.

Large workload policy:

- Provider fetches use pages/chunks.
- Task args pass IDs only.
- Each task handles a bounded amount of work.
- Scanner tasks enqueue due imports in batches using database locks.

## Release sync workflow

Sync default scope:

- followed artists
- `Follow.is_ignored=False`

Artist sync:

- use MusicBrainz as canonical source
- refresh artist metadata
- refresh aliases
- update name, sort name, type, disambiguation, and country
- update `Artist.last_refreshed_at`
- update `SyncState`

Release sync:

- browse release groups for the artist
- upsert `ReleaseGroup`
- preserve date precision
- preserve secondary types
- store raw MusicBrainz payload
- update `ReleaseGroup.last_refreshed_at`
- create or update `ReleaseEvent`

`Release` rows are optional in this phase unless the MusicBrainz client method used by the task returns concrete releases. The required phase outcome is reliable release-group/event discovery without duplicate user notifications.

## Sync summary contract

Add a tested service helper for later UI:

`get_artist_sync_summary(artist)`

Return fields:

- artist ID
- artist name
- artist last refreshed time
- release sync status
- release sync last started time
- release sync last succeeded time
- release sync last failed time
- retry-after time
- display-safe error summary

This phase does not build the UI. It stores and exposes the data contract so the UI can show last checked time, status, retry window, and source error summary without reading raw provider payloads directly.

## Notification fanout

Release sync does not send email.

When a new or newly notifiable `ReleaseEvent` appears:

1. enqueue notification fanout task
2. find followers for the release event artist
3. respect `Follow.is_ignored`
4. respect notification preference
5. create `Notification` rows by cadence bucket

The existing unique constraint on `Notification` prevents duplicate rows per user/event/bucket.

Cadence buckets:

- `instant`: queue soon
- `daily`: current UTC date bucket
- `weekly`: ISO week bucket
- `off`: no notification row

Email delivery stays out of scope for this phase.

## Failure and retry policy

Transient failures:

- network timeout
- provider 5xx
- provider rate limit
- broker disconnect during enqueue

Behavior:

- Celery retry with exponential backoff where safe.
- Provider rate limit updates `SyncState.retry_after` or equivalent import state.
- Requeued work must use IDs, not provider payloads.

Auth failures:

- provider account marked `failed` or `revoked`
- recurring import stops
- one-shot import marks `ImportRun.failed`

Permanent mapping failures:

- current row skipped or current run failed, depending scope
- error message redacted
- raw payload redacted before persistence

Crash safety:

- every task can run more than once
- DB constraints and update-or-create patterns prevent duplicates
- scanners can re-enqueue due rows from Postgres

## Rate limits and locks

Use Redis only for shared cross-worker controls where Postgres would be too heavy:

- provider rate counters
- short locks for provider-account import enqueue
- short locks for artist sync enqueue

Durable state remains in Postgres. Redis keys must have TTLs. Loss of Redis must not corrupt data; it may slow or temporarily pause work.

MusicBrainz still must respect one request per second per app/IP by default.

## Security

- Encrypt stored provider tokens.
- Require separate token encryption key when encrypted token storage is enabled.
- Redact tokens, API keys, API secrets, signed URLs, and session-like values before persistence.
- Celery task args contain IDs only.
- Admin must not search encrypted token values.
- Admin list displays must not expose token material.
- Services must verify row ownership before mutating user-owned objects.
- Logs must include IDs and statuses, not secrets or raw provider payloads.
- Provider failures shown to users must be display-safe summaries.

## Operations

Compose updates:

- add RabbitMQ service with health check
- add Redis service with health check
- replace generic worker/scheduler placeholders with dedicated Celery worker/beat services
- keep web service unchanged except env

Useful commands:

- `celery -A config worker -Q imports --loglevel=info`
- `celery -A config worker -Q sync --loglevel=info`
- `celery -A config worker -Q notifications --loglevel=info`
- `celery -A config worker -Q maintenance --loglevel=info`
- `celery -A config beat --loglevel=info`

Local development should still support direct service function calls in tests without running workers.

## Testing

Use TDD.

Required coverage:

- Celery app imports and config uses RabbitMQ env setting.
- Compose defines RabbitMQ, Redis, dedicated workers, and beat.
- `ProviderAccount` constraints, status transitions, and token encryption.
- Missing encryption key fails when encrypted token storage is requested.
- Token redaction in errors and stored payloads.
- Last.fm import creates `ImportRun` and `ImportCandidate` rows.
- ListenBrainz import creates candidates without persisting one-shot token.
- Saved ListenBrainz provider account import decrypts token only inside service boundary.
- Plain text import creates candidates.
- MBID match creates or links canonical `Artist`.
- ambiguous name match stays pending.
- accepted candidate creates `Follow`.
- ignored candidate does not become followed.
- release sync upserts release groups/events.
- release sync stores sync summary state.
- notification fanout respects cadence and dedupes.
- scanner tasks use bounded batches.
- repeated task execution does not duplicate rows.
- rate-limit failure records retry time.
- auth failure marks provider account/import failed.

Coverage floor stays at 96% and only moves up.

## Implementation split

Plan 1: task infrastructure and import workflow.

- Celery/RabbitMQ/Redis/django-celery-beat wiring
- provider account model and token encryption
- import services and tasks
- plain text import
- candidate matching and review service
- scanner for due provider account imports

Plan 2: release sync and notification fanout.

- MusicBrainz artist/release-group sync service
- sync summary service
- notification fanout service and task
- due sync scanner
- retry/rate-limit behavior for sync jobs

This split keeps each implementation plan reviewable while preserving one production architecture.
