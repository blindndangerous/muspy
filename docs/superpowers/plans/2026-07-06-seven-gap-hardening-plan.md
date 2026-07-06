# Seven Gap Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the seven user-facing gaps found after the invite signup pass.

**Architecture:** Each task lands as an atomic commit with its own tests. Keep changes server-rendered, accessible, and aligned with existing Django views, forms, models, services, and templates. Avoid schema changes unless the task cannot be completed cleanly without one.

**Tech Stack:** Django 6, pytest, Django templates, Celery task hooks, existing releasewatch services.

---

## Atomic commit rule

Each task below must produce one or more self-contained commits. Do not mix tasks in the same commit. Every commit must use:

```text
Co-authored-by: blindndangerous <20344049+blindndangerous@users.noreply.github.com>
Co-authored-by: Codex <codex@openai.com>
```

## Task 1: Import start UI

**Goal:** Let authenticated users start imports from the web UI.

**Files:**
- Modify: `releasewatch/forms.py`
- Modify: `releasewatch/views.py`
- Modify: `releasewatch/urls.py`
- Modify: `templates/releasewatch/import_list.html`
- Test: `tests/test_import_review_views.py`

**Behavior:**
- `/imports/` shows accessible forms for:
  - Plain text artist names.
  - Last.fm username import.
  - ListenBrainz username import.
- POST creates an `ImportRun` for the current user, applies existing import creation rate limit `RATE_LIMIT_IMPORT_CREATE`, and redirects to the import detail page.
- Plain text imports may process synchronously through `start_plain_text_import`.
- Last.fm and ListenBrainz imports enqueue existing Celery import task or call the existing service through a task-safe path, without adding live network calls to tests.
- Validation errors render on `/imports/` with `role="alert"` error summary.
- Cross-user import visibility stays blocked.

**Verification:**
- Add failing tests first for render, each POST path, validation, rate limiting, and ownership.
- Run `uv run pytest tests/test_import_review_views.py tests/test_import_workflows.py -q`.
- Run `uv run ruff check releasewatch tests/test_import_review_views.py`.

## Task 2: Unfollow and remove artists

**Goal:** Let authenticated users stop following artists and remove ignored follows from their list.

**Files:**
- Modify: `releasewatch/forms.py`
- Modify: `releasewatch/views.py`
- Modify: `releasewatch/urls.py`
- Modify: `templates/releasewatch/follow_list.html`
- Test: `tests/test_dashboard_follow_views.py`

**Behavior:**
- Follow list shows a POST button for each follow.
- Following artists can be unfollowed.
- Ignored artists can be removed from the list.
- Actions require login, POST, CSRF, and ownership.
- The app does not delete shared `Artist` rows.

**Verification:**
- Add failing tests first for unfollow, ignored removal, cross-user protection, POST-only behavior, and CSRF.
- Run `uv run pytest tests/test_dashboard_follow_views.py tests/test_artist_search_follow_views.py -q`.
- Run `uv run ruff check releasewatch tests/test_dashboard_follow_views.py`.

## Task 3: Account and profile settings UI

**Goal:** Let users manage account basics without Django admin.

**Files:**
- Modify: `releasewatch/forms.py`
- Modify: `releasewatch/views.py`
- Modify: `releasewatch/urls.py`
- Modify: `templates/base.html`
- Create: `templates/releasewatch/account_settings.html`
- Test: `tests/test_account_settings_view.py`

**Behavior:**
- Authenticated users can update email, timezone, and country.
- Authenticated users can change password with Django password validation.
- Email changes clear `UserProfile.email_verified_at`.
- Settings page is linked in authenticated nav.
- Form labels, help text, and errors are accessible.

**Verification:**
- Add failing tests first for GET, email/profile update, password change, invalid password, login required, and email verification reset.
- Run `uv run pytest tests/test_account_settings_view.py tests/test_settings_security.py -q`.
- Run `uv run ruff check releasewatch tests/test_account_settings_view.py`.

## Task 4: Password reset templates and links

**Goal:** Make Django password reset flow usable and branded.

**Files:**
- Modify: `templates/registration/login.html`
- Create or modify:
  - `templates/registration/password_reset_form.html`
  - `templates/registration/password_reset_done.html`
  - `templates/registration/password_reset_confirm.html`
  - `templates/registration/password_reset_complete.html`
  - `templates/registration/password_reset_email.html`
  - `templates/registration/password_reset_subject.txt`
- Test: `tests/test_auth_password_reset_views.py`

**Behavior:**
- Login page links to password reset.
- Password reset views render accessible templates.
- Email uses existing Django email backend.
- Password reset confirm accepts valid token and rejects invalid token.

**Verification:**
- Add failing tests first for route rendering, login link, email send, confirm page, and completion page.
- Run `uv run pytest tests/test_auth_password_reset_views.py tests/test_dashboard_follow_views.py -q`.
- Run `uv run ruff check tests/test_auth_password_reset_views.py`.

## Task 5: Email unsubscribe and verification views

**Goal:** Wire public links for notification opt-out and email verification.

**Files:**
- Modify: `releasewatch/models.py` only if a token field is already insufficient.
- Modify: `releasewatch/notifications.py`
- Modify: `releasewatch/notification_delivery.py`
- Modify: `releasewatch/views.py`
- Modify: `releasewatch/urls.py`
- Create templates as needed under `templates/releasewatch/`.
- Test: `tests/test_email_link_views.py`

**Behavior:**
- Notification email includes an unsubscribe URL.
- Visiting unsubscribe with a valid signed token disables notification email for that user.
- Email verification uses a signed token and sets `UserProfile.email_verified_at`.
- Invalid tokens return controlled 404 or 400 pages without exposing account data.

**Verification:**
- Add failing tests first for token generation, unsubscribe success, invalid token rejection, email verification success, and no account data leakage.
- Run `uv run pytest tests/test_email_link_views.py tests/test_notification_delivery.py tests/test_notifications.py -q`.
- Run `uv run ruff check releasewatch tests/test_email_link_views.py`.

## Task 6: Cover art and artist images

**Goal:** Show useful visual media where available without making pages depend on image availability.

**Files:**
- Modify or create upstream client/service files under `releasewatch/`.
- Modify artist/release templates as needed.
- Test: `tests/test_cover_art.py`

**Behavior:**
- Release detail and artist detail may display cover art or artist image URL from MusicBrainz/Cover Art Archive data when available.
- Missing images use accessible text fallback, not broken UI.
- Images have meaningful alt text.
- Tests use mocked HTTP only.

**Verification:**
- Add failing tests first for image URL extraction, missing-image fallback, and template alt text.
- Run `uv run pytest tests/test_cover_art.py tests/test_public_release_views.py -q`.
- Run `uv run ruff check releasewatch tests/test_cover_art.py`.

## Task 7: Public API, sitemap, FAQ, about, and contact pages

**Goal:** Restore low-risk legacy public surface area useful for users and integrations.

**Files:**
- Modify: `releasewatch/views.py`
- Modify: `releasewatch/urls.py`
- Create templates:
  - `templates/releasewatch/about.html`
  - `templates/releasewatch/faq.html`
  - `templates/releasewatch/contact.html`
  - `templates/releasewatch/sitemap.xml`
- Create API views or serializers under `releasewatch/` if needed.
- Test: `tests/test_public_static_and_api_views.py`

**Behavior:**
- Public about, FAQ, contact, and sitemap routes render.
- API v1 read-only endpoints expose public release and artist data as JSON.
- API does not expose user emails, feed tokens, notification settings, or private imports.
- Routes are documented in README or development docs.

**Verification:**
- Add failing tests first for static pages, sitemap content type, public API release list, public API artist detail, and private field exclusion.
- Run `uv run pytest tests/test_public_static_and_api_views.py tests/test_public_release_views.py -q`.
- Run `uv run ruff check releasewatch tests/test_public_static_and_api_views.py`.

## Final verification

After all seven tasks:

- Run `uv run ruff check .`.
- Run `uv run coverage run -m pytest`.
- Run `uv run coverage report`.
- Run `uv run bandit -c pyproject.toml -r config releasewatch`.
- Run `uv run python manage.py check`.
- Rebuild Podman app stack.
- Push all commits.
- Watch GitHub Actions until CI passes.
