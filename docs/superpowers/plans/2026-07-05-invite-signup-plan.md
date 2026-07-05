# Invite Signup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let invited users create accounts without opening unrestricted public signup.

**Architecture:** Reuse the existing `Invite` model and Django auth. Add a signup form, a public invite URL, and an accessible template. Successful signup increments invite usage and logs the new user in.

**Tech Stack:** Django 6, Django auth, pytest, server-rendered templates.

---

### Task 1: Signup behavior tests

**Files:**
- Create: `tests/test_signup_views.py`

- [ ] Add tests for valid invite rendering, account creation, invite usage increment, invalid invite rejection, expired invite rejection, duplicate usernames, and accessible form fields.
- [ ] Run `uv run pytest tests/test_signup_views.py -q`.
- [ ] Expected first result: failures because `/accounts/signup/<code>/` does not exist.

### Task 2: Signup implementation

**Files:**
- Modify: `releasewatch/forms.py`
- Modify: `releasewatch/views.py`
- Modify: `releasewatch/urls.py`
- Create: `templates/registration/signup.html`
- Modify: `templates/registration/login.html`

- [ ] Add `InviteSignupForm` based on `UserCreationForm`.
- [ ] Add `signup_with_invite(request, code)` that rejects unusable invites, saves the user, increments `Invite.uses`, logs in, and redirects to the dashboard.
- [ ] Add route `accounts/signup/<str:code>/`.
- [ ] Add an accessible signup template with labels, errors, CSRF, username, email, password, and password confirmation.
- [ ] Add login-page copy telling invite holders to open their invite link.
- [ ] Run `uv run pytest tests/test_signup_views.py -q`.

### Task 3: Navigation and attribution docs

**Files:**
- Modify: `templates/base.html`
- Modify: `tests/test_accessibility_templates.py`
- Modify: `README.md`
- Modify: `docs/development.md`

- [ ] Keep anonymous navigation clear with `Log in`.
- [ ] Keep footer MusicBrainz text linked to `https://musicbrainz.org/`.
- [ ] Add README attribution policy with both coauthor trailers.
- [ ] Document how to create a local invite and use it for real-data testing.
- [ ] Run targeted UI and docs-adjacent checks.

### Task 4: Verification, local stack, and publishing

- [ ] Run `uv run ruff check .`.
- [ ] Run `uv run pytest`.
- [ ] Run `uv run coverage run -m pytest` and `uv run coverage report`.
- [ ] Run `uv run bandit -c pyproject.toml -r config releasewatch`.
- [ ] Run `uv run python manage.py check`.
- [ ] Rebuild or restart the Podman web container so local changes appear at `http://localhost:8000/`.
- [ ] Commit with both coauthor trailers.
- [ ] Push.
- [ ] Watch GitHub Actions until CI passes.
