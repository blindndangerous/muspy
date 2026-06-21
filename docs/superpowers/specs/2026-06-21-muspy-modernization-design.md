# Muspy Modernization Design

Date: 2026-06-21

## Status

Approved design direction from brainstorming. Implementation has not started.

## Goal

Build a modern Muspy successor in the `blindndangerous/muspy` fork while keeping the legacy code only as historical reference. The new app tracks followed artists, discovers releases, and notifies users through web UI, email, RSS, and iCal.

## Non-Goals

- Do not port the Python 2 and Django 1.3 app line by line.
- Do not preserve old API behavior when it conflicts with security or maintainability.
- Do not enable public signup for MVP.
- Do not add Spotify, Apple Music, Bandcamp, or provider-specific streaming integrations in MVP.
- Do not build a single-page app.

## Product Scope

MVP is invite-only and aimed at personal or small trusted-user use before any public service launch.

Users can:

- follow MusicBrainz artists
- search and confirm artists manually
- import candidate artists from Last.fm, ListenBrainz, and pasted plain text
- review imported candidates before following them
- ignore imported artists so repeated imports do not re-add them
- view followed artists and releases
- choose notification cadence
- subscribe to RSS and iCal feeds through revocable token URLs
- delete their account and associated user data

## Stack

- Python 3.14 target, with Python 3.13 fallback if dependency support requires it.
- Django 6.
- PostgreSQL 18.
- `uv` for Python version, dependency, lockfile, and command execution.
- Server-rendered Django templates.
- Minimal JavaScript only where it improves the workflow.
- Podman Compose and Docker Compose compatible container setup.
- Bare-metal setup supported with `uv` and `DATABASE_URL`.

## Repository Strategy

Use `blindndangerous/muspy` for provenance and continuity. Legacy code remains available for reference. The modern app should be cleanly implemented under a new package named `releasewatch`.

Old Muspy code may be consulted to answer behavior questions, but should not be copied unless there is a specific reason and the decision is documented.

## Architecture

The modern implementation is a Django project with one main domain app, `releasewatch`.

Main modules:

- `releasewatch.models`: persistent domain model.
- `releasewatch.musicbrainz`: MusicBrainz client and parsing.
- `releasewatch.listenbrainz`: ListenBrainz import and fresh-release client.
- `releasewatch.lastfm`: Last.fm import client.
- `releasewatch.notifications`: notification planning, batching, unsubscribe, and send logging.
- `releasewatch.feeds`: RSS and iCal generation.
- `releasewatch.tasks`: background task entry points.
- `releasewatch.views`: server-rendered pages and forms.
- `releasewatch.admin`: Django admin configuration.

Background work uses Django 6 Tasks API from application code. If production-ready third-party task backends are not mature enough during implementation, use a small internal task wrapper so Celery or another durable backend can be swapped without spreading backend-specific calls through domain code.

Periodic scheduler commands only enqueue work. Workers perform imports, artist refreshes, release sync, cover refresh, digest generation, and email sending.

## Data Model Sketch

Core entities:

- `User`: Django auth user.
- `UserProfile`: notification cadence, country preference, email verification state, timezone.
- `Invite`: invite code, creator, max uses, expiration.
- `Artist`: MusicBrainz artist MBID, canonical name, sort name, disambiguation, type, country, raw payload, refresh timestamp.
- `ArtistAlias`: artist alias metadata.
- `Follow`: user, artist, per-follow settings, ignored flag, created timestamp.
- `ReleaseGroup`: MusicBrainz release-group MBID, title, primary type, secondary types, first-release date with precision, raw payload.
- `Release`: concrete release MBID, release group, country, date precision, media/status, raw payload.
- `ReleaseEvent`: normalized event that can become visible or notifiable.
- `NotificationPreference`: global notification settings; per-artist overrides remain a future extension.
- `Notification`: user, release event, cadence bucket, status, sent/failed timestamps.
- `FeedToken`: revocable RSS/iCal token scoped to user and feed type.
- `ImportRun`: source, user, status, raw import data, review state.
- `SyncState`: artist/release sync timestamps, errors, retry schedule.
- `EmailLog`: metadata and provider response/error, with body pruning by retention policy.

Important constraints:

- canonical MBIDs are unique
- follows are unique per user and artist
- notifications are deduped per user, release event, and cadence bucket
- tasks are idempotent and retry-safe through constraints
- raw upstream payloads use PostgreSQL JSONB where useful

## Notification Design

Users choose notification cadence:

- off
- daily digest
- weekly digest
- instant

Default is daily digest.

"Instant" still means queued and sent soon by workers, not sent inside sync jobs. All notifications pass through dedupe, rate-limit, unsubscribe, email verification, and preference checks.

Future release behavior is configurable:

- show future releases in web/feed views
- optionally hide future releases from RSS
- send release-date reminders for releases discovered early
- avoid instant alerts for year-only dates

Digest batching exists from MVP to avoid release floods.

## Release Date Handling

Store date precision:

- year
- year and month
- full date

Display incomplete dates explicitly:

- `2026`
- `June 2026`
- `June 21, 2026`

iCal behavior:

- full date: event on that date
- year-month: event on last day of month, marked tentative
- year-only: excluded by default

## Known Muspy Pain Points Addressed

Open issues and forks of `alexkay/muspy` were reviewed before this design. MVP must address these lessons:

- notification timing and digest controls, from issues 9, 23, 59, and 62
- visible iCal links and tokenized feed URLs, from issue 68 and PR 19
- robust artist search confirmation, from issues 57 and 69
- artist rename and deadname handling, from issue 65
- sync explainability for missing releases, from issues 61 and 67
- country-aware release date modeling, from issue 32
- tested account deletion, from issue 55
- email deliverability basics, from issues 14 and 56
- modern cover art source behavior, from issue 46
- reviewable import flow and ignored artists, from issue 8

Fork lessons:

- `mbaechtold/muspy` explored Python 3, Django modernization, Celery, PostgreSQL-compatible tests, env settings, Django admin, async MusicBrainz fetching, rate limiting, iCal library usage, and UI improvements.
- These are useful design signals, not code to copy.

## Security Baseline

Configuration:

- secrets from environment variables
- production fails fast if required secrets are missing
- container and production examples default to `DEBUG=False`
- dev-only bootstraps guarded by explicit flags

Auth and authorization:

- invite-only signup
- Django password reset flow
- email verification before email notifications
- every user-owned object checked by owner
- feed/iCal tokens are scoped and revocable
- no private data access by public user ID

Web and data safety:

- CSRF on mutating forms
- secure cookies and secure headers in production docs
- no inline secrets in templates or logs
- account deletion verified by tests
- retention pruning for logs and raw payloads

Email:

- List-Unsubscribe header
- unsubscribe links do not authenticate the user or expose account data
- send attempts and failures logged

Abuse control:

- rate limits for signup, password reset, imports, search, and refresh-now actions
- MusicBrainz and ListenBrainz rate limits respected

Supply chain:

- dependencies locked with `uv.lock`
- dependency audit in CI
- Django deploy checks in deployment verification

## Testing and Quality Bar

Use TDD wherever practical. No production code for new behavior without a failing test first.

Coverage goal is comprehensive behavior coverage across the whole app, not only files touched in a given task.

Test categories:

- domain model constraints and deletion behavior
- views, forms, and authorization
- task idempotency and retry behavior
- MusicBrainz, ListenBrainz, and Last.fm clients with recorded or fixture payloads
- import review and ignored artist behavior
- release date precision and country-specific releases
- notification cadence and dedupe
- RSS and iCal token behavior
- email verification, unsubscribe, List-Unsubscribe, and send logging
- account deletion completeness
- accessibility smoke checks for key pages
- security regression tests for auth, CSRF, token secrecy, and cross-user access

Run targeted tests for every red-green cycle, then affected groups, then full verification before completion. Add regression tests whenever implementation uncovers a new edge case.

## Git checkpoints and rollback

Use commits as checkpoints throughout the project.

Checkpoint rules:

- commit planning docs before implementation starts
- commit after each implementation phase reaches verified green state
- keep commits small enough to revert one behavior without losing unrelated work
- never mix broad refactors with feature behavior unless the refactor is required for that behavior
- record the last known good commit in `docs/agent-handoff.md`
- before risky changes, create a named checkpoint branch or tag
- after failures, prefer targeted revert or follow-up fix commits over rewriting shared history

Each checkpoint commit should include:

- tests or verification commands run
- scope of the change
- known gaps if any remain

The implementation plan should define phase checkpoints before coding begins.

## Tooling

Use `uv` commands:

- `uv sync --locked --all-extras --dev`
- `uv run pytest`
- `uv run manage.py migrate`
- `uv run manage.py runserver`
- `uv lock`

Use `pyproject.toml` and `uv.lock` as dependency truth. Avoid `requirements.txt` for the modern app unless a deployment target requires an exported file.

## Runtime Modes

Bare metal:

- `uv sync`
- local PostgreSQL or configured `DATABASE_URL`
- `uv run manage.py migrate`
- `uv run manage.py runserver`

Containers:

- Compose file compatible with Docker Compose and Podman Compose
- PostgreSQL 18 service
- web service
- worker service
- scheduler service if needed
- health checks

Docs must show both:

- `podman-compose up --build`
- `docker compose up --build`

## Dev Admin Bootstrap

Provide a dev-only management command such as `ensure_dev_admin`.

Requirements:

- reads username, email, and password from environment variables
- refuses to run unless `DEBUG=True` or `ALLOW_DEV_ADMIN_BOOTSTRAP=1`
- never commits a real password
- documented in setup docs for local visual/admin testing

## Documentation Plan

Keep these docs current:

- `README.md`: purpose, quick start, test commands
- `docs/architecture.md`: modules and data flow
- `docs/development.md`: TDD workflow, fixtures, coverage, local admin bootstrap
- `docs/deployment.md`: bare metal, Podman Compose, Docker Compose, env vars, migrations, health checks
- `docs/security.md`: threat model, feed tokens, deletion, dependency checks
- `docs/agent-handoff.md`: compact recovery and current phase

## Implementation Phases

1. Repository setup and planning docs.
2. Modern scaffold.
3. Domain model.
4. Upstream clients.
5. Follow and import workflows.
6. Release sync.
7. Notifications.
8. Feeds.
9. UI.
10. Hardening, documentation, deployment smoke tests.

## Context Compact Recovery

After context compact, read in this order:

1. `docs/agent-handoff.md`
2. this design spec
3. implementation plan, once written
4. `git status`

Continue from the first unchecked task in the plan or the next action recorded in handoff.
