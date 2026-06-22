# Upstream Clients Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build tested provider clients for MusicBrainz, ListenBrainz, and Last.fm without adding sync workflow code yet.

**Architecture:** Add `releasewatch/upstreams/` with shared HTTP/error/rate-limit helpers and one small provider module per service. Clients use synchronous `httpx.Client`, typed dataclasses, injected transports for tests, and provider-specific error mapping.

**Tech Stack:** Python 3.14, Django 6 settings, `httpx`, `pytest`, `coverage`, `ruff`, `bandit`.

---

## File structure

- Create `releasewatch/upstreams/__init__.py`: public exports.
- Create `releasewatch/upstreams/base.py`: shared dataclasses, exceptions, date precision parser, request helper, redaction helper, response metadata, and simple throttle.
- Create `releasewatch/upstreams/musicbrainz.py`: MusicBrainz client.
- Create `releasewatch/upstreams/listenbrainz.py`: ListenBrainz client.
- Create `releasewatch/upstreams/lastfm.py`: Last.fm client.
- Modify `config/settings.py`: upstream timeout, user agent/contact, and Last.fm API setting defaults.
- Modify `pyproject.toml`: add `httpx` dependency.
- Create `tests/test_upstream_base.py`: shared behavior tests.
- Create `tests/test_musicbrainz_client.py`: MusicBrainz tests.
- Create `tests/test_listenbrainz_client.py`: ListenBrainz tests.
- Create `tests/test_lastfm_client.py`: Last.fm tests.
- Modify `docs/development.md`: describe upstream mock-test policy and env names.
- Modify `docs/agent-handoff.md`: record checkpoint and next step.

## Task 1: Add dependency and settings tests

**Files:**

- Modify: `tests/test_settings_security.py`
- Modify: `pyproject.toml`
- Modify: `config/settings.py`

- [ ] **Step 1: Write failing settings/dependency tests**

Append to `tests/test_settings_security.py`:

```python


def test_upstream_client_settings_have_safe_defaults(settings):
    assert settings.UPSTREAM_HTTP_TIMEOUT_SECONDS == 10
    assert settings.UPSTREAM_USER_AGENT.startswith("muspy/")
    assert "example.invalid" in settings.UPSTREAM_CONTACT
    assert settings.LASTFM_API_KEY == ""
    assert settings.LASTFM_API_SECRET == ""
```

Append to `tests/test_quality_config.py`:

```python


def test_httpx_is_project_dependency():
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert any(dependency.startswith("httpx") for dependency in config["project"]["dependencies"])
```

- [ ] **Step 2: Run red tests**

```powershell
uv run pytest tests/test_settings_security.py::test_upstream_client_settings_have_safe_defaults tests/test_quality_config.py::test_httpx_is_project_dependency -q
```

Expected: fails because settings and dependency are missing.

- [ ] **Step 3: Add dependency and settings**

In `pyproject.toml`, add to `[project].dependencies`:

```toml
    "httpx>=0.28,<1.0",
```

In `config/settings.py`, add:

```python
UPSTREAM_HTTP_TIMEOUT_SECONDS = int(os.environ.get("UPSTREAM_HTTP_TIMEOUT_SECONDS", "10"))
UPSTREAM_CONTACT = os.environ.get("UPSTREAM_CONTACT", "https://example.invalid/contact")
UPSTREAM_USER_AGENT = os.environ.get(
    "UPSTREAM_USER_AGENT",
    f"muspy/{os.environ.get('MUSPY_VERSION', '0.1.0')} ({UPSTREAM_CONTACT})",
)
LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY", "")
LASTFM_API_SECRET = os.environ.get("LASTFM_API_SECRET", "")
```

- [ ] **Step 4: Lock dependency**

```powershell
uv lock
```

Expected: `uv.lock` updates with `httpx` and transitive dependencies.

- [ ] **Step 5: Run green tests**

```powershell
uv run pytest tests/test_settings_security.py::test_upstream_client_settings_have_safe_defaults tests/test_quality_config.py::test_httpx_is_project_dependency -q
uv run ruff check config tests/test_settings_security.py tests/test_quality_config.py
```

Expected: both tests pass and Ruff passes.

- [ ] **Step 6: Commit checkpoint**

```powershell
git add pyproject.toml uv.lock config/settings.py tests/test_settings_security.py tests/test_quality_config.py
git commit -m "chore: add upstream client settings"
```

## Task 2: Add shared upstream base client

**Files:**

- Create: `releasewatch/upstreams/__init__.py`
- Create: `releasewatch/upstreams/base.py`
- Create: `tests/test_upstream_base.py`

- [ ] **Step 1: Write failing base tests**

Create `tests/test_upstream_base.py`:

```python
from datetime import date
import time

import httpx
import pytest

from releasewatch.models import DatePrecision
from releasewatch.upstreams.base import (
    FixedIntervalThrottle,
    UpstreamAuthError,
    UpstreamClient,
    UpstreamNotFound,
    UpstreamRateLimited,
    UpstreamUnavailable,
    parse_partial_date,
    redact_upstream_payload,
)


def test_parse_partial_date_preserves_precision():
    assert parse_partial_date("2026") == (date(2026, 1, 1), DatePrecision.YEAR)
    assert parse_partial_date("2026-06") == (date(2026, 6, 1), DatePrecision.MONTH)
    assert parse_partial_date("2026-06-21") == (date(2026, 6, 21), DatePrecision.DAY)
    assert parse_partial_date("") == (None, "")


def test_redact_upstream_payload_removes_nested_secrets():
    payload = {"token": "secret", "nested": {"api_key": "secret"}, "safe": "value"}

    assert redact_upstream_payload(payload) == {
        "token": "[redacted]",
        "nested": {"api_key": "[redacted]"},
        "safe": "value",
    }


def test_base_client_maps_common_http_errors():
    def handler(request):
        return httpx.Response(429, json={"error": "slow down"})

    client = UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(UpstreamRateLimited):
        client.get_json("/limited")


@pytest.mark.parametrize(
    ("status_code", "exception_type"),
    [
        (401, UpstreamAuthError),
        (403, UpstreamAuthError),
        (404, UpstreamNotFound),
        (500, UpstreamUnavailable),
        (503, UpstreamRateLimited),
    ],
)
def test_base_client_maps_status_codes(status_code, exception_type):
    def handler(request):
        return httpx.Response(status_code, json={"error": "provider error"})

    client = UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(exception_type):
        client.get_json("/path")


def test_base_client_sets_user_agent_and_accept_json():
    seen_headers = {}

    def handler(request):
        seen_headers.update(request.headers)
        return httpx.Response(200, json={"ok": True})

    client = UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.get_json("/path") == {"ok": True}
    assert seen_headers["user-agent"] == "muspy/0.1.0 (https://example.invalid/contact)"
    assert seen_headers["accept"] == "application/json"


def test_fixed_interval_throttle_waits_between_calls(monkeypatch):
    current = {"value": 100.0}
    sleeps = []
    monkeypatch.setattr(time, "monotonic", lambda: current["value"])
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))

    throttle = FixedIntervalThrottle(interval_seconds=1.0)
    throttle.wait()
    throttle.wait()

    assert sleeps == [1.0]
```

- [ ] **Step 2: Run red tests**

```powershell
uv run pytest tests/test_upstream_base.py -q
```

Expected: import failure because `releasewatch.upstreams` does not exist.

- [ ] **Step 3: Implement base module**

Create `releasewatch/upstreams/base.py` with:

- `UpstreamError` base exception storing `provider`, `status_code`, and redacted `payload`.
- Specific exceptions named in tests.
- `parse_partial_date(value: str)`.
- `redact_upstream_payload(value)`, delegating to `releasewatch.models.redact_payload`.
- `FixedIntervalThrottle.wait()`.
- `UpstreamClient.get_json(path, params=None, headers=None)` using `httpx.Client`.

Create `releasewatch/upstreams/__init__.py` exporting base symbols.

- [ ] **Step 4: Run green tests**

```powershell
uv run pytest tests/test_upstream_base.py -q
uv run ruff check releasewatch/upstreams tests/test_upstream_base.py
```

Expected: tests and Ruff pass.

- [ ] **Step 5: Commit checkpoint**

```powershell
git add releasewatch/upstreams tests/test_upstream_base.py
git commit -m "feat: add upstream client base"
```

## Task 3: Add MusicBrainz client

**Files:**

- Create: `releasewatch/upstreams/musicbrainz.py`
- Modify: `releasewatch/upstreams/__init__.py`
- Create: `tests/test_musicbrainz_client.py`

- [ ] **Step 1: Write failing MusicBrainz tests**

Create `tests/test_musicbrainz_client.py` with tests that use `httpx.MockTransport` and assert:

- requests go to `/ws/2/artist/<mbid>` with `fmt=json`.
- `User-Agent` is set from settings.
- aliases map to `UpstreamArtist.aliases`.
- `life-span.ended` and unrelated fields remain only in `raw_payload`.
- release group browse maps `first-release-date` to date plus precision.
- 503 maps to `UpstreamRateLimited`.
- throttle waits between two calls.

- [ ] **Step 2: Run red tests**

```powershell
uv run pytest tests/test_musicbrainz_client.py -q
```

Expected: import failure for `MusicBrainzClient`.

- [ ] **Step 3: Implement MusicBrainz client**

Create dataclasses in `base.py` if not already added:

- `UpstreamArtist`
- `UpstreamArtistAlias`
- `UpstreamReleaseGroup`
- `UpstreamRelease`

Create `MusicBrainzClient` with:

- `base_url="https://musicbrainz.org/ws/2"`
- default `FixedIntervalThrottle(1.0)`
- `lookup_artist(mbid)`
- `search_artists(query, limit=10, offset=0)`
- `browse_release_groups(artist_mbid, limit=100, offset=0)`
- `lookup_release_group(mbid)`

- [ ] **Step 4: Run green tests**

```powershell
uv run pytest tests/test_musicbrainz_client.py tests/test_upstream_base.py -q
uv run ruff check releasewatch/upstreams tests/test_musicbrainz_client.py tests/test_upstream_base.py
```

Expected: tests and Ruff pass.

- [ ] **Step 5: Commit checkpoint**

```powershell
git add releasewatch/upstreams tests/test_musicbrainz_client.py
git commit -m "feat: add musicbrainz client"
```

## Task 4: Add ListenBrainz client

**Files:**

- Create: `releasewatch/upstreams/listenbrainz.py`
- Modify: `releasewatch/upstreams/__init__.py`
- Create: `tests/test_listenbrainz_client.py`

- [ ] **Step 1: Write failing ListenBrainz tests**

Create `tests/test_listenbrainz_client.py` with tests that assert:

- root URL is `https://api.listenbrainz.org`.
- authenticated calls send `Authorization: Token <token>`.
- rate headers are parsed into response metadata.
- imported artist rows map to `ImportedArtist`.
- 401 maps to `UpstreamAuthError`.
- 429 maps to `UpstreamRateLimited` with reset seconds when present.

- [ ] **Step 2: Run red tests**

```powershell
uv run pytest tests/test_listenbrainz_client.py -q
```

Expected: import failure for `ListenBrainzClient`.

- [ ] **Step 3: Implement ListenBrainz client**

Create `ImportedArtist` dataclass in `base.py`.

Create `ListenBrainzClient` with:

- `get_user_artists(username, token, count=100, offset=0)`
- private header builder that returns `{"Authorization": f"Token {token}"}`
- response metadata parser for `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset-In`

- [ ] **Step 4: Run green tests**

```powershell
uv run pytest tests/test_listenbrainz_client.py tests/test_upstream_base.py -q
uv run ruff check releasewatch/upstreams tests/test_listenbrainz_client.py
```

Expected: tests and Ruff pass.

- [ ] **Step 5: Commit checkpoint**

```powershell
git add releasewatch/upstreams tests/test_listenbrainz_client.py
git commit -m "feat: add listenbrainz client"
```

## Task 5: Add Last.fm client

**Files:**

- Create: `releasewatch/upstreams/lastfm.py`
- Modify: `releasewatch/upstreams/__init__.py`
- Create: `tests/test_lastfm_client.py`

- [ ] **Step 1: Write failing Last.fm tests**

Create `tests/test_lastfm_client.py` with tests that assert:

- API calls include `method`, `api_key`, `format=json`, and provider parameters.
- user top artists map to `ImportedArtist`.
- Last.fm error code `29` maps to `UpstreamRateLimited`.
- Last.fm auth/key errors map to `UpstreamAuthError`.
- API secret is not present in exception payload.
- paging parameters are sent.

- [ ] **Step 2: Run red tests**

```powershell
uv run pytest tests/test_lastfm_client.py -q
```

Expected: import failure for `LastFmClient`.

- [ ] **Step 3: Implement Last.fm client**

Create `LastFmClient` with:

- `base_url="https://ws.audioscrobbler.com/2.0/"`
- `get_user_top_artists(username, period="overall", limit=100, page=1)`
- error mapper for JSON payloads with `error`.

Do not implement scrobbling in this task.

- [ ] **Step 4: Run green tests**

```powershell
uv run pytest tests/test_lastfm_client.py tests/test_upstream_base.py -q
uv run ruff check releasewatch/upstreams tests/test_lastfm_client.py
```

Expected: tests and Ruff pass.

- [ ] **Step 5: Commit checkpoint**

```powershell
git add releasewatch/upstreams tests/test_lastfm_client.py
git commit -m "feat: add lastfm client"
```

## Task 6: Add documentation and full verification

**Files:**

- Modify: `docs/development.md`
- Modify: `docs/agent-handoff.md`

- [ ] **Step 1: Update docs**

In `docs/development.md`, add a short "Upstream provider tests" section:

```markdown
## Upstream provider tests

Provider client tests use `httpx.MockTransport`. Do not add live network calls to
the test suite. Configure provider credentials through environment variables:

- `UPSTREAM_HTTP_TIMEOUT_SECONDS`
- `UPSTREAM_CONTACT`
- `UPSTREAM_USER_AGENT`
- `LASTFM_API_KEY`
- `LASTFM_API_SECRET`
```

Update `docs/agent-handoff.md`:

- Current phase: upstream clients complete.
- Last known good commit: short hash from Task 5.
- Next required step: write sync/import workflow plan.

- [ ] **Step 2: Run full verification**

```powershell
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
$env:SECRET_KEY='upstream-test-secret'
uv run coverage erase
uv run coverage run -m pytest tests/test_settings_security.py tests/test_quality_config.py tests/test_upstream_base.py tests/test_musicbrainz_client.py tests/test_listenbrainz_client.py tests/test_lastfm_client.py -q
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-domain.sqlite3'
uv run coverage run --append -m pytest tests/test_domain_models.py tests/test_dev_admin_command.py tests/test_project_smoke.py tests/test_container_files.py tests/test_ci_workflow.py -q
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL -ErrorAction SilentlyContinue
uv run coverage report
uv run ruff check .
uv run bandit -c pyproject.toml -r config releasewatch
uv run python manage.py check
Remove-Item .tmp-domain.sqlite3* -ErrorAction SilentlyContinue
```

Expected:

- tests pass
- coverage stays at or above 96%
- Ruff passes
- Bandit reports no issues
- Django check reports no issues

- [ ] **Step 3: Commit final upstream checkpoint**

```powershell
git add docs/development.md docs/agent-handoff.md
git commit -m "docs: record upstream client checkpoint"
git tag checkpoint/upstream-clients
git status --short --branch --untracked-files=all
```

Expected: clean worktree and tag exists.
