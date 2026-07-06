# Modern Gap Fill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill high- and medium-value modern user-facing gaps found after the legacy comparison.

**Architecture:** Keep the app server-rendered, accessible, invite-oriented, and modern. Do not preserve legacy URLs or legacy authenticated write API behavior. Each task lands as an atomic commit with tests and review.

**Tech Stack:** Django 6, pytest, Django templates, Celery hooks, PostgreSQL/SQLite test URLs, GitHub Actions.

---

## Ranked Scope

1. High: Account deletion UI.
2. High: Resend email verification UI.
3. High: Per-release-type notification filters.
4. Medium: Public API filters and pagination.
5. Medium: Starred releases.

Not in scope:

- Legacy URL compatibility redirects.
- Authenticated write API for follows/imports/account mutation.

## Commit Rule

Every task commit must use:

```text
Co-authored-by: blindndangerous <20344049+blindndangerous@users.noreply.github.com>
Co-authored-by: Codex <codex@openai.com>
```

## Task 1: Account Deletion UI

**Goal:** Let authenticated users delete their account and user-owned data without Django admin.

**Files:**

- Modify: `releasewatch/forms.py`
- Modify: `releasewatch/views.py`
- Modify: `releasewatch/urls.py`
- Modify: `templates/base.html`
- Create: `templates/releasewatch/account_delete.html`
- Test: `tests/test_account_delete_view.py`

**Behavior:**

- Authenticated users can open a delete-account page from account settings or authenticated navigation.
- POST requires a deliberate confirmation field such as `confirm_delete`.
- Successful deletion logs the user out and deletes the `User`; cascading deletes remove owned follows, preferences, feed tokens, provider accounts, imports, notifications, and email logs.
- Shared `Artist`, `ReleaseGroup`, `Release`, and `ReleaseEvent` rows are not deleted.
- GET renders accessible warning text; invalid POST re-renders with `role="alert"`.
- Anonymous users are redirected to login.

**Verification:**

- Add failing tests for GET, login required, invalid confirmation, successful deletion/logout, user-owned cascade, shared release data preserved, and CSRF.
- Run: `$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.pytest-task1-modern-gap.sqlite3'; uv run pytest tests/test_account_delete_view.py tests/test_account_settings_view.py -q`.
- Run: `uv run ruff check releasewatch tests/test_account_delete_view.py`.

## Task 2: Resend Email Verification UI

**Goal:** Let users request a new verification email after signup or email change.

**Files:**

- Modify: `releasewatch/notifications.py`
- Modify: `releasewatch/notification_delivery.py` or create `releasewatch/email_delivery.py`
- Modify: `releasewatch/views.py`
- Modify: `releasewatch/urls.py`
- Modify: `templates/releasewatch/account_settings.html`
- Create: `templates/releasewatch/email_verification_sent.html` if useful
- Test: `tests/test_email_verification_request_view.py`

**Behavior:**

- Authenticated users with unverified email can POST to send a verification email.
- Authenticated users with already verified email get a harmless success/info response without sending another email.
- Email uses existing signed verification token and `PUBLIC_BASE_URL`.
- View is POST-only, CSRF-protected, login-required, and rate-limited.
- Account settings shows a verification status and resend control.
- Email send failures produce controlled messages and no token leakage.

**Verification:**

- Add failing tests for unverified resend, verified no-op, POST-only, login required, rate limit, token validates, and settings page control visibility.
- Run: `$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.pytest-task2-modern-gap.sqlite3'; uv run pytest tests/test_email_verification_request_view.py tests/test_email_link_views.py tests/test_account_settings_view.py -q`.
- Run: `uv run ruff check releasewatch tests/test_email_verification_request_view.py`.

## Task 3: Per-Release-Type Notification Filters

**Goal:** Let users filter notification fanout by release type.

**Files:**

- Modify: `releasewatch/models.py`
- Create migration under `releasewatch/migrations/`
- Modify: `releasewatch/forms.py`
- Modify: `releasewatch/notifications.py`
- Modify: `templates/releasewatch/notification_settings.html`
- Test: `tests/test_notification_type_filters.py`
- Modify existing notification settings/fanout tests as needed.

**Behavior:**

- `NotificationPreference` stores booleans for album, single, EP, live, compilation, remix, and other release groups.
- Defaults preserve current behavior: all release types included.
- Notification settings page exposes accessible checkboxes.
- Fanout skips release events whose primary/secondary type is disabled.
- Unknown or blank type maps to "other".

**Verification:**

- Add failing tests for default inclusion, each disabled type skip, unknown type handled by other, form save, settings page labels, and migration defaults.
- Run: `$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.pytest-task3-modern-gap.sqlite3'; uv run pytest tests/test_notification_type_filters.py tests/test_notification_settings_view.py tests/test_notifications.py -q`.
- Run: `uv run ruff check releasewatch tests/test_notification_type_filters.py`.

## Task 4: Public API Filters and Pagination

**Goal:** Make public read-only API useful for integrations without exposing private data.

**Files:**

- Modify: `releasewatch/api.py`
- Modify: `releasewatch/views.py`
- Modify: `README.md`
- Test: `tests/test_public_api_filters.py`

**Behavior:**

- `/api/v1/releases/` accepts `limit`, `offset`, `artist_mbid`, and `since`.
- `limit` defaults to 100 and is capped at 100.
- Invalid params return 400 JSON errors without stack traces.
- `since` filters events updated after an ISO datetime or by event id only if codebase patterns already support that safely.
- API remains read-only and excludes private fields.
- README documents params.

**Verification:**

- Add failing tests for limit, cap, offset, artist filter, invalid params, private-field exclusion, and POST 405.
- Run: `$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.pytest-task4-modern-gap.sqlite3'; uv run pytest tests/test_public_api_filters.py tests/test_public_static_and_api_views.py -q`.
- Run: `uv run ruff check releasewatch tests/test_public_api_filters.py`.

## Task 5: Starred Releases

**Goal:** Let users save releases they care about without changing follow state.

**Files:**

- Modify: `releasewatch/models.py`
- Create migration under `releasewatch/migrations/`
- Modify: `releasewatch/forms.py`
- Modify: `releasewatch/views.py`
- Modify: `releasewatch/urls.py`
- Modify: `templates/releasewatch/release_detail.html`
- Modify: `templates/releasewatch/release_list.html`
- Create: `templates/releasewatch/starred_release_list.html`
- Test: `tests/test_starred_releases.py`

**Behavior:**

- Authenticated users can star/unstar visible release events with POST-only actions.
- Starred releases list is private to the authenticated user.
- Repeated star/unstar is idempotent.
- Cross-user visibility is blocked.
- Public release pages keep working for anonymous users.
- Buttons have clear accessible labels.

**Verification:**

- Add failing tests for star, unstar, idempotency, login required, POST-only, private list, anonymous release detail behavior, and accessible labels.
- Run: `$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.pytest-task5-modern-gap.sqlite3'; uv run pytest tests/test_starred_releases.py tests/test_public_release_views.py -q`.
- Run: `uv run ruff check releasewatch tests/test_starred_releases.py`.

## Final Verification

- Run `uv run ruff check .`.
- Run `uv run coverage run -m pytest`.
- Run `uv run coverage report`.
- Run `uv run bandit -c pyproject.toml -r config releasewatch`.
- Run `uv run python manage.py check`.
- Rebuild Podman stack.
- Push commits.
- Watch GitHub Actions until CI passes.

