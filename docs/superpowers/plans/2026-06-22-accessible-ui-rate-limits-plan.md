# Accessible UI and Rate Limits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build WCAG 2.2 AA server-rendered UI for public release browsing and authenticated user workflows, with Redis-backed rate limiting included.

**Architecture:** Add focused Django forms, views, URL routes, templates, CSS, and a small internal cache-backed rate limiter. Keep public pages read-only and anonymous-safe; keep authenticated pages scoped to `request.user`. Use TDD for every page, form, and rate-limit behavior.

**Tech Stack:** Python 3.14, Django 6, PostgreSQL 18, Redis via Django `RedisCache`, Celery 5.6, `uv`, pytest, Ruff, Bandit, Podman Compose.

---

## File Structure

- Create `releasewatch/rate_limits.py`: fixed-window cache-backed rate limit helpers.
- Create `tests/test_rate_limits.py`: rate limit identity, hashing, 429, and cache failure coverage.
- Modify `config/settings.py`: configure Redis cache and rate limit settings.
- Create `templates/429.html` and `templates/503.html`: accessible error pages.
- Create `templates/base.html`: shared accessible shell.
- Create `static/releasewatch/site.css`: minimal accessible styling.
- Create `releasewatch/templatetags/__init__.py` and `releasewatch/templatetags/releasewatch_ui.py`: release date and display helpers.
- Create `tests/test_accessibility_templates.py`: landmarks, labels, headings, skip link, table caption, focus CSS smoke tests.
- Modify `releasewatch/views.py`: public pages and authenticated workflows.
- Modify `config/urls.py`: UI routes.
- Create `releasewatch/forms.py`: search, follow, import review, and notification settings forms.
- Create `tests/test_public_release_views.py`: anonymous public release pages.
- Create `tests/test_dashboard_follow_views.py`: login-required dashboard/follows.
- Create `tests/test_artist_search_follow_views.py`: MusicBrainz search and follow workflow.
- Create `tests/test_import_review_views.py`: import review workflow.
- Create `tests/test_notification_settings_view.py`: notification settings workflow.
- Create templates under `templates/releasewatch/`: public release pages, dashboard, follows, search, imports, settings.
- Modify `docs/development.md`, `docs/security.md`, and `docs/agent-handoff.md`: record UI/rate-limit operations and checkpoint.

Use explicit local uv on Windows:

```powershell
C:\Users\blind\.local\bin\uv.exe
```

For DB-backed tests:

```powershell
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-ui-rate-limits.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
```

Cleanup after DB-backed commands:

```powershell
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-ui-rate-limits.sqlite3* -ErrorAction SilentlyContinue
```

---

## Task 1: Rate Limits, Redis Cache Settings, and Error Pages

**Files:**

- Create: `releasewatch/rate_limits.py`
- Create: `tests/test_rate_limits.py`
- Modify: `config/settings.py`
- Create: `templates/429.html`
- Create: `templates/503.html`
- Modify: `tests/test_settings_security.py`

- [ ] **Step 1: Write failing rate limit tests**

Create `tests/test_rate_limits.py`:

```python
import pytest
from django.core.cache import cache, caches
from django.test import RequestFactory, override_settings


@pytest.fixture(autouse=True)
def locmem_cache(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "rate-limit-tests",
        }
    }
    caches.close_all()
    cache.clear()
    yield
    cache.clear()
    caches.close_all()


def test_check_rate_limit_allows_requests_below_limit():
    from releasewatch.rate_limits import check_rate_limit

    request = RequestFactory().get("/artists/search/", REMOTE_ADDR="192.0.2.10")

    first = check_rate_limit(
        request,
        scope="artist-search",
        limit=2,
        window_seconds=60,
        identity="ip",
    )
    second = check_rate_limit(
        request,
        scope="artist-search",
        limit=2,
        window_seconds=60,
        identity="ip",
    )

    assert first.allowed is True
    assert first.remaining == 1
    assert second.allowed is True
    assert second.remaining == 0


def test_check_rate_limit_blocks_requests_over_limit():
    from releasewatch.rate_limits import check_rate_limit

    request = RequestFactory().get("/artists/search/", REMOTE_ADDR="192.0.2.10")

    check_rate_limit(request, scope="artist-search", limit=1, window_seconds=60, identity="ip")
    result = check_rate_limit(
        request,
        scope="artist-search",
        limit=1,
        window_seconds=60,
        identity="ip",
    )

    assert result.allowed is False
    assert result.remaining == 0
    assert result.retry_after_seconds > 0


def test_rate_limit_cache_key_hashes_sensitive_values():
    from releasewatch.rate_limits import rate_limit_key

    key = rate_limit_key(
        scope="login",
        identity_parts=("username", "person@example.test"),
        window_seconds=60,
        now_seconds=120,
    )

    assert "person@example.test" not in key
    assert "username" in key
    assert key.startswith("releasewatch:ratelimit:login:username:")


def test_user_or_ip_identity_uses_user_id_for_authenticated_user(django_user_model):
    from releasewatch.rate_limits import identity_parts_for_request

    user = django_user_model.objects.create_user(username="listener", password=None)
    request = RequestFactory().get("/dashboard/", REMOTE_ADDR="192.0.2.10")
    request.user = user

    assert identity_parts_for_request(request, "user_or_ip") == ("user", str(user.id))


def test_user_or_ip_identity_uses_ip_for_anonymous_user():
    from django.contrib.auth.models import AnonymousUser

    from releasewatch.rate_limits import identity_parts_for_request

    request = RequestFactory().get("/releases/", REMOTE_ADDR="192.0.2.10")
    request.user = AnonymousUser()

    assert identity_parts_for_request(request, "user_or_ip") == ("ip", "192.0.2.10")


def test_rate_limited_response_uses_429_template():
    from releasewatch.rate_limits import rate_limited_response

    response = rate_limited_response(RequestFactory().get("/"), retry_after_seconds=30)

    assert response.status_code == 429
    assert response["Retry-After"] == "30"
    assert b"Too many requests" in response.content


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.dummy.DummyCache",
        }
    }
)
def test_dummy_cache_backend_is_rejected_for_protected_limits():
    from releasewatch.rate_limits import RateLimitUnavailable, check_rate_limit

    request = RequestFactory().get("/artists/search/", REMOTE_ADDR="192.0.2.10")

    with pytest.raises(RateLimitUnavailable):
        check_rate_limit(request, scope="artist-search", limit=1, window_seconds=60, identity="ip")
```

Append to `tests/test_settings_security.py`:

```python
def test_redis_cache_is_configured_from_redis_url(settings):
    assert settings.CACHES["default"]["BACKEND"] == "django.core.cache.backends.redis.RedisCache"
    assert settings.CACHES["default"]["LOCATION"] == settings.REDIS_URL


def test_rate_limit_settings_are_bounded(settings):
    assert settings.RATE_LIMIT_ARTIST_SEARCH_AUTHENTICATED == (60, 60)
    assert settings.RATE_LIMIT_FOLLOW_MUTATION == (60, 60)
    assert settings.RATE_LIMIT_IMPORT_CREATE == (10, 3600)
    assert settings.RATE_LIMIT_IMPORT_REVIEW == (120, 60)
    assert settings.RATE_LIMIT_NOTIFICATION_SETTINGS == (30, 60)
```

- [ ] **Step 2: Run red tests**

```powershell
Remove-Item Env:DEBUG,Env:DATABASE_URL,Env:PROVIDER_TOKEN_ENCRYPTION_KEY -ErrorAction SilentlyContinue
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_rate_limits.py tests/test_settings_security.py::test_redis_cache_is_configured_from_redis_url tests/test_settings_security.py::test_rate_limit_settings_are_bounded -q
$exit=$LASTEXITCODE
Remove-Item Env:SECRET_KEY,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
exit $exit
```

Expected: fails because `releasewatch.rate_limits` and settings are missing.

- [ ] **Step 3: Add Redis cache and rate limit settings**

In `config/settings.py`, after `REDIS_URL`:

```python
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

RATE_LIMIT_ARTIST_SEARCH_AUTHENTICATED = (
    _env_int("RATE_LIMIT_ARTIST_SEARCH_AUTHENTICATED_COUNT", default=60, minimum=1, maximum=600),
    _env_int("RATE_LIMIT_ARTIST_SEARCH_AUTHENTICATED_WINDOW", default=60, minimum=1, maximum=3600),
)
RATE_LIMIT_FOLLOW_MUTATION = (
    _env_int("RATE_LIMIT_FOLLOW_MUTATION_COUNT", default=60, minimum=1, maximum=600),
    _env_int("RATE_LIMIT_FOLLOW_MUTATION_WINDOW", default=60, minimum=1, maximum=3600),
)
RATE_LIMIT_IMPORT_CREATE = (
    _env_int("RATE_LIMIT_IMPORT_CREATE_COUNT", default=10, minimum=1, maximum=200),
    _env_int("RATE_LIMIT_IMPORT_CREATE_WINDOW", default=3600, minimum=60, maximum=86400),
)
RATE_LIMIT_IMPORT_REVIEW = (
    _env_int("RATE_LIMIT_IMPORT_REVIEW_COUNT", default=120, minimum=1, maximum=1000),
    _env_int("RATE_LIMIT_IMPORT_REVIEW_WINDOW", default=60, minimum=1, maximum=3600),
)
RATE_LIMIT_NOTIFICATION_SETTINGS = (
    _env_int("RATE_LIMIT_NOTIFICATION_SETTINGS_COUNT", default=30, minimum=1, maximum=300),
    _env_int("RATE_LIMIT_NOTIFICATION_SETTINGS_WINDOW", default=60, minimum=1, maximum=3600),
)
```

- [ ] **Step 4: Add rate limit helper**

Create `releasewatch/rate_limits.py`:

```python
import hashlib
import time
from dataclasses import dataclass
from typing import Literal

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

Identity = Literal["ip", "user", "user_or_ip"]


class RateLimitUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


def check_rate_limit(
    request: HttpRequest,
    *,
    scope: str,
    limit: int,
    window_seconds: int,
    identity: Identity = "user_or_ip",
) -> RateLimitResult:
    now_seconds = int(time.time())
    identity_parts = identity_parts_for_request(request, identity)
    key = rate_limit_key(
        scope=scope,
        identity_parts=identity_parts,
        window_seconds=window_seconds,
        now_seconds=now_seconds,
    )
    window_started_at = now_seconds - (now_seconds % window_seconds)
    retry_after_seconds = window_started_at + window_seconds - now_seconds
    timeout = retry_after_seconds + 1

    try:
        cache.add(key, 0, timeout=timeout)
        count = cache.incr(key)
    except Exception as error:
        raise RateLimitUnavailable("Rate limit backend is unavailable.") from error

    if count is None:
        raise RateLimitUnavailable("Rate limit backend did not return a counter.")

    remaining = max(limit - count, 0)
    return RateLimitResult(
        allowed=count <= limit,
        limit=limit,
        remaining=remaining,
        retry_after_seconds=max(retry_after_seconds, 1),
    )


def identity_parts_for_request(request: HttpRequest, identity: Identity) -> tuple[str, str]:
    if identity == "user":
        if request.user.is_authenticated:
            return ("user", str(request.user.id))
        return ("anonymous", client_ip(request))
    if identity == "user_or_ip" and request.user.is_authenticated:
        return ("user", str(request.user.id))
    return ("ip", client_ip(request))


def rate_limit_key(
    *,
    scope: str,
    identity_parts: tuple[str, str],
    window_seconds: int,
    now_seconds: int,
) -> str:
    identity_name, identity_value = identity_parts
    digest = hashlib.sha256(identity_value.encode("utf-8")).hexdigest()
    window = now_seconds // window_seconds
    return f"releasewatch:ratelimit:{scope}:{identity_name}:{digest}:{window_seconds}:{window}"


def client_ip(request: HttpRequest) -> str:
    return request.META.get("REMOTE_ADDR", "")


def rate_limited_response(
    request: HttpRequest,
    *,
    retry_after_seconds: int,
) -> HttpResponse:
    response = render(
        request,
        "429.html",
        {"retry_after_seconds": retry_after_seconds},
        status=429,
    )
    response["Retry-After"] = str(retry_after_seconds)
    return response


def rate_limit_unavailable_response(request: HttpRequest) -> HttpResponse:
    return render(request, "503.html", status=503)
```

- [ ] **Step 5: Add error templates**

Create `templates/429.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Too many requests</title>
  </head>
  <body>
    <main>
      <h1>Too many requests</h1>
      <p>Please wait {{ retry_after_seconds }} seconds, then try again.</p>
      <p><a href="/">Go to release overview</a></p>
    </main>
  </body>
</html>
```

Create `templates/503.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Service temporarily unavailable</title>
  </head>
  <body>
    <main>
      <h1>Service temporarily unavailable</h1>
      <p>This action cannot be processed right now. Please try again soon.</p>
      <p><a href="/">Go to release overview</a></p>
    </main>
  </body>
</html>
```

- [ ] **Step 6: Run green rate limit tests**

```powershell
Remove-Item Env:DEBUG,Env:DATABASE_URL,Env:PROVIDER_TOKEN_ENCRYPTION_KEY -ErrorAction SilentlyContinue
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_rate_limits.py tests/test_settings_security.py::test_redis_cache_is_configured_from_redis_url tests/test_settings_security.py::test_rate_limit_settings_are_bounded -q
C:\Users\blind\.local\bin\uv.exe run ruff check config/settings.py releasewatch/rate_limits.py tests/test_rate_limits.py tests/test_settings_security.py
$exit=$LASTEXITCODE
Remove-Item Env:SECRET_KEY,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
exit $exit
```

Expected: tests pass and Ruff passes.

- [ ] **Step 7: Commit checkpoint**

```powershell
git add config/settings.py releasewatch/rate_limits.py tests/test_rate_limits.py tests/test_settings_security.py templates/429.html templates/503.html
git commit -m "feat: add cache backed rate limits"
```

---

## Task 2: Base Template, CSS, and UI Helpers

**Files:**

- Create: `templates/base.html`
- Create: `static/releasewatch/site.css`
- Create: `releasewatch/templatetags/__init__.py`
- Create: `releasewatch/templatetags/releasewatch_ui.py`
- Create: `tests/test_accessibility_templates.py`
- Modify: `config/urls.py` only if static helper tests need URL resolution

- [ ] **Step 1: Write failing accessibility template tests**

Create `tests/test_accessibility_templates.py`:

```python
from datetime import date

from django.template import Context, Template

from releasewatch.models import DatePrecision


def render_template(source, context=None):
    return Template(source).render(Context(context or {}))


def test_base_template_has_skip_link_main_landmark_and_navigation(client):
    response = client.get("/")

    assert response.status_code == 200
    html = response.content.decode()
    assert 'href="#main-content"' in html
    assert '<main id="main-content"' in html
    assert 'aria-label="Primary"' in html


def test_focus_visible_css_rule_exists():
    css = open("static/releasewatch/site.css", encoding="utf-8").read()

    assert ":focus-visible" in css
    assert "outline" in css
    assert "scroll-margin-top" in css


def test_release_date_filter_formats_precision():
    html = render_template(
        "{% load releasewatch_ui %}"
        "{{ value|release_date:precision }}",
        {"value": date(2026, 6, 22), "precision": DatePrecision.DAY},
    )

    assert "June 22, 2026" in html


def test_release_date_filter_formats_month_precision():
    html = render_template(
        "{% load releasewatch_ui %}"
        "{{ value|release_date:precision }}",
        {"value": date(2026, 6, 1), "precision": DatePrecision.MONTH},
    )

    assert "June 2026" in html


def test_release_date_filter_formats_year_precision():
    html = render_template(
        "{% load releasewatch_ui %}"
        "{{ value|release_date:precision }}",
        {"value": date(2026, 1, 1), "precision": DatePrecision.YEAR},
    )

    assert "2026" in html
```

- [ ] **Step 2: Run red tests**

```powershell
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-ui-rate-limits.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_accessibility_templates.py -q
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-ui-rate-limits.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: fails because home route/template/CSS/tag helpers are missing.

- [ ] **Step 3: Create base template**

Create `templates/base.html`:

```html
{% load static %}
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}Muspy{% endblock %}</title>
    <link rel="stylesheet" href="{% static 'releasewatch/site.css' %}">
  </head>
  <body>
    <a class="skip-link" href="#main-content">Skip to main content</a>
    <header class="site-header">
      <a class="site-name" href="{% url 'releasewatch:home' %}">Muspy</a>
      <nav aria-label="Primary">
        <ul class="nav-list">
          <li><a href="{% url 'releasewatch:home' %}">Home</a></li>
          <li><a href="{% url 'releasewatch:release_list' %}">Releases</a></li>
          {% block authenticated_nav %}{% endblock %}
        </ul>
      </nav>
    </header>
    {% if messages %}
      <section class="messages" aria-label="Status messages" aria-live="polite">
        {% for message in messages %}
          <p>{{ message }}</p>
        {% endfor %}
      </section>
    {% endif %}
    <main id="main-content" tabindex="-1">
      {% block content %}{% endblock %}
    </main>
    <footer class="site-footer">
      <p>Release data from MusicBrainz.</p>
    </footer>
  </body>
</html>
```

- [ ] **Step 4: Create CSS**

Create `static/releasewatch/site.css`:

```css
:root {
  color-scheme: light;
  --color-text: #1f2328;
  --color-muted: #59636e;
  --color-link: #0645ad;
  --color-border: #8c959f;
  --color-background: #ffffff;
  --color-surface: #f6f8fa;
  --color-focus: #0b57d0;
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
}

* {
  box-sizing: border-box;
}

html {
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.5;
}

body {
  margin: 0;
  color: var(--color-text);
  background: var(--color-background);
}

a {
  color: var(--color-link);
}

a:focus,
button:focus,
input:focus,
select:focus,
textarea:focus {
  outline: none;
}

:focus-visible {
  outline: 3px solid var(--color-focus);
  outline-offset: 3px;
  scroll-margin-top: 5rem;
  scroll-margin-bottom: 2rem;
}

.skip-link {
  position: absolute;
  top: var(--space-2);
  left: var(--space-2);
  transform: translateY(-200%);
  padding: var(--space-2) var(--space-3);
  color: var(--color-background);
  background: var(--color-text);
  z-index: 10;
}

.skip-link:focus {
  transform: translateY(0);
}

.site-header,
.site-footer {
  padding: var(--space-4);
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
}

.site-footer {
  border-top: 1px solid var(--color-border);
  border-bottom: 0;
}

.site-name {
  font-weight: 700;
  font-size: 1.25rem;
}

.nav-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  padding: 0;
  margin: var(--space-3) 0 0;
  list-style: none;
}

main {
  max-width: 72rem;
  padding: var(--space-4);
}

.messages,
.error-summary {
  margin: var(--space-4);
  padding: var(--space-4);
  border: 2px solid var(--color-border);
  background: var(--color-surface);
}

.field {
  margin-block: var(--space-4);
}

label,
legend {
  display: block;
  font-weight: 700;
}

input,
select,
textarea,
button,
.button {
  min-height: 2.75rem;
  padding: var(--space-2) var(--space-3);
  font: inherit;
}

button,
.button {
  border: 1px solid var(--color-text);
  color: var(--color-background);
  background: var(--color-text);
  cursor: pointer;
  text-decoration: none;
}

table {
  width: 100%;
  border-collapse: collapse;
}

caption {
  text-align: left;
  font-weight: 700;
  margin-block: var(--space-3);
}

th,
td {
  padding: var(--space-2);
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  vertical-align: top;
}

.muted {
  color: var(--color-muted);
}
```

- [ ] **Step 5: Add template helpers**

Create `releasewatch/templatetags/__init__.py`:

```python
```

Create `releasewatch/templatetags/releasewatch_ui.py`:

```python
from django import template

from releasewatch.models import DatePrecision

register = template.Library()


@register.filter
def release_date(value, precision):
    if value is None:
        return "Unknown date"
    if precision == DatePrecision.YEAR:
        return str(value.year)
    if precision == DatePrecision.MONTH:
        return value.strftime("%B %Y")
    return value.strftime("%B %-d, %Y")
```

On Windows, `strftime("%-d")` may not work. If tests fail on Windows, use:

```python
return f"{value.strftime('%B')} {value.day}, {value.year}"
```

Preferred implementation should use the portable f-string version.

- [ ] **Step 6: Add temporary home and release URL names**

Add minimal public views in `releasewatch/views.py`; Task 3 replaces their empty querysets with real release data:

```python
from django.shortcuts import render


def home(request):
    return render(request, "releasewatch/home.html", {"recent_events": [], "upcoming_events": []})


def release_list(request):
    return render(request, "releasewatch/release_list.html", {"events": []})
```

Create minimal templates:

`templates/releasewatch/home.html`:

```html
{% extends "base.html" %}
{% block title %}Release overview{% endblock %}
{% block content %}
  <h1>Release overview</h1>
{% endblock %}
```

`templates/releasewatch/release_list.html`:

```html
{% extends "base.html" %}
{% block title %}Releases{% endblock %}
{% block content %}
  <h1>Releases</h1>
{% endblock %}
```

Modify `config/urls.py`:

```python
from django.contrib import admin
from django.urls import include, path

from releasewatch.views import health

urlpatterns = [
    path("", include("releasewatch.urls")),
    path("health/", health, name="health"),
    path("admin/", admin.site.urls),
]
```

Create `releasewatch/urls.py`:

```python
from django.urls import path

from releasewatch import views

app_name = "releasewatch"

urlpatterns = [
    path("", views.home, name="home"),
    path("releases/", views.release_list, name="release_list"),
]
```

- [ ] **Step 7: Run green base template tests**

```powershell
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-ui-rate-limits.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_accessibility_templates.py tests/test_project_smoke.py -q
C:\Users\blind\.local\bin\uv.exe run ruff check config/urls.py releasewatch/views.py releasewatch/urls.py releasewatch/templatetags/releasewatch_ui.py tests/test_accessibility_templates.py
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-ui-rate-limits.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: tests pass and Ruff passes.

- [ ] **Step 8: Commit checkpoint**

```powershell
git add config/urls.py releasewatch/views.py releasewatch/urls.py releasewatch/templatetags templates static tests/test_accessibility_templates.py
git commit -m "feat: add accessible ui shell"
```

---

## Task 3: Public Release Pages

**Files:**

- Modify: `releasewatch/views.py`
- Modify: `releasewatch/urls.py`
- Modify: `templates/releasewatch/home.html`
- Modify: `templates/releasewatch/release_list.html`
- Create: `templates/releasewatch/artist_detail.html`
- Create: `templates/releasewatch/release_detail.html`
- Create: `tests/test_public_release_views.py`

- [ ] **Step 1: Write failing public page tests**

Create `tests/test_public_release_views.py`:

```python
from datetime import date
from uuid import uuid4

import pytest
from django.urls import reverse

from releasewatch.models import Artist, DatePrecision, ReleaseEvent, ReleaseGroup

pytestmark = pytest.mark.django_db


def create_event(*, visible=True, event_date=date(2026, 6, 22), artist_name="Fugazi"):
    artist = Artist.objects.create(mbid=uuid4(), name=artist_name, sort_name=artist_name)
    group = ReleaseGroup.objects.create(
        mbid=uuid4(),
        artist=artist,
        title="Repeater",
        primary_type="Album",
    )
    event = ReleaseEvent.objects.create(
        release_group=group,
        event_date=event_date,
        date_precision=DatePrecision.DAY if event_date else "",
        visible=visible,
    )
    return artist, group, event


def test_home_page_is_public_and_lists_visible_releases(client):
    artist, _, event = create_event()
    create_event(visible=False)

    response = client.get(reverse("releasewatch:home"))

    assert response.status_code == 200
    assert b"Release overview" in response.content
    assert artist.name.encode() in response.content
    assert str(event.release_group).encode() in response.content
    assert response.content.count(b"Repeater") == 1


def test_release_list_is_public_and_hides_invisible_events(client):
    create_event()
    hidden_artist, _, _ = create_event(visible=False, artist_name="Hidden Artist")

    response = client.get(reverse("releasewatch:release_list"))

    assert response.status_code == 200
    assert b"Releases" in response.content
    assert b"Repeater" in response.content
    assert hidden_artist.name.encode() not in response.content
    assert b"<caption>Visible release events</caption>" in response.content


def test_artist_detail_is_public_and_lists_visible_events(client):
    artist, _, _ = create_event()

    response = client.get(reverse("releasewatch:artist_detail", args=[artist.id]))

    assert response.status_code == 200
    assert artist.name.encode() in response.content
    assert b"Repeater" in response.content


def test_artist_detail_returns_404_when_artist_has_no_visible_events(client):
    artist, _, _ = create_event(visible=False)

    response = client.get(reverse("releasewatch:artist_detail", args=[artist.id]))

    assert response.status_code == 404


def test_release_detail_is_public_for_visible_event(client):
    _, _, event = create_event()

    response = client.get(reverse("releasewatch:release_detail", args=[event.id]))

    assert response.status_code == 200
    assert b"Repeater" in response.content
    assert b"June 22, 2026" in response.content


def test_release_detail_returns_404_for_invisible_event(client):
    _, _, event = create_event(visible=False)

    response = client.get(reverse("releasewatch:release_detail", args=[event.id]))

    assert response.status_code == 404
```

- [ ] **Step 2: Run red tests**

```powershell
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-ui-rate-limits.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_public_release_views.py -q
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-ui-rate-limits.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: fails because detail routes/views/templates are missing or current minimal pages do not list events.

- [ ] **Step 3: Implement public views**

In `releasewatch/views.py`, add imports:

```python
from django.shortcuts import get_object_or_404, render

from releasewatch.models import Artist, ReleaseEvent
```

Add helpers and views:

```python
def visible_release_events():
    return (
        ReleaseEvent.objects.select_related("release_group__artist", "release")
        .filter(visible=True)
        .order_by("event_date", "release_group__artist__sort_name", "release_group__title", "id")
    )


def home(request):
    events = visible_release_events()
    today = timezone.localdate()
    return render(
        request,
        "releasewatch/home.html",
        {
            "recent_events": events.filter(event_date__lt=today).order_by(
                "-event_date",
                "release_group__artist__sort_name",
                "release_group__title",
                "id",
            )[:10],
            "upcoming_events": events.filter(event_date__gte=today)[:10],
        },
    )


def release_list(request):
    return render(
        request,
        "releasewatch/release_list.html",
        {"events": visible_release_events()[:100]},
    )


def artist_detail(request, artist_id: int):
    artist = get_object_or_404(
        Artist.objects.filter(release_groups__events__visible=True).distinct(),
        pk=artist_id,
    )
    events = visible_release_events().filter(release_group__artist=artist)
    return render(request, "releasewatch/artist_detail.html", {"artist": artist, "events": events})


def release_detail(request, event_id: int):
    event = get_object_or_404(visible_release_events(), pk=event_id)
    return render(request, "releasewatch/release_detail.html", {"event": event})
```

Make sure `timezone` is imported from `django.utils`.

- [ ] **Step 4: Add public routes**

In `releasewatch/urls.py`:

```python
urlpatterns = [
    path("", views.home, name="home"),
    path("artists/<int:artist_id>/", views.artist_detail, name="artist_detail"),
    path("releases/", views.release_list, name="release_list"),
    path("releases/<int:event_id>/", views.release_detail, name="release_detail"),
]
```

- [ ] **Step 5: Add public templates**

Update `templates/releasewatch/home.html`:

```html
{% extends "base.html" %}
{% load releasewatch_ui %}

{% block title %}Release overview{% endblock %}

{% block content %}
  <h1>Release overview</h1>

  <h2>Upcoming releases</h2>
  {% include "releasewatch/includes/release_event_table.html" with events=upcoming_events caption="Upcoming visible release events" %}

  <h2>Recent releases</h2>
  {% include "releasewatch/includes/release_event_table.html" with events=recent_events caption="Recent visible release events" %}
{% endblock %}
```

Create `templates/releasewatch/includes/release_event_table.html`:

```html
{% load releasewatch_ui %}

{% if events %}
  <table>
    <caption>{{ caption }}</caption>
    <thead>
      <tr>
        <th scope="col">Artist</th>
        <th scope="col">Release</th>
        <th scope="col">Date</th>
        <th scope="col">Country</th>
        <th scope="col">Status</th>
      </tr>
    </thead>
    <tbody>
      {% for event in events %}
        <tr>
          <td><a href="{% url 'releasewatch:artist_detail' event.release_group.artist_id %}">{{ event.release_group.artist.name }}</a></td>
          <td><a href="{% url 'releasewatch:release_detail' event.id %}">{{ event.release_group.title }}</a></td>
          <td>{{ event.event_date|release_date:event.date_precision }}</td>
          <td>{{ event.country|default:"Unknown country" }}</td>
          <td>{{ event.release.status|default:"Unknown status" }}</td>
        </tr>
      {% endfor %}
    </tbody>
  </table>
{% else %}
  <p>No releases found.</p>
{% endif %}
```

Update `templates/releasewatch/release_list.html`:

```html
{% extends "base.html" %}

{% block title %}Releases{% endblock %}

{% block content %}
  <h1>Releases</h1>
  {% include "releasewatch/includes/release_event_table.html" with events=events caption="Visible release events" %}
{% endblock %}
```

Create `templates/releasewatch/artist_detail.html`:

```html
{% extends "base.html" %}

{% block title %}{{ artist.name }}{% endblock %}

{% block content %}
  <h1>{{ artist.name }}</h1>
  {% if artist.disambiguation %}
    <p>{{ artist.disambiguation }}</p>
  {% endif %}
  {% include "releasewatch/includes/release_event_table.html" with events=events caption="Visible release events for this artist" %}
{% endblock %}
```

Create `templates/releasewatch/release_detail.html`:

```html
{% extends "base.html" %}
{% load releasewatch_ui %}

{% block title %}{{ event.release_group.title }}{% endblock %}

{% block content %}
  <h1>{{ event.release_group.title }}</h1>
  <dl>
    <dt>Artist</dt>
    <dd><a href="{% url 'releasewatch:artist_detail' event.release_group.artist_id %}">{{ event.release_group.artist.name }}</a></dd>
    <dt>Date</dt>
    <dd>{{ event.event_date|release_date:event.date_precision }}</dd>
    <dt>Country</dt>
    <dd>{{ event.country|default:"Unknown country" }}</dd>
    <dt>Status</dt>
    <dd>{{ event.release.status|default:"Unknown status" }}</dd>
  </dl>
{% endblock %}
```

- [ ] **Step 6: Run green public page tests**

```powershell
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-ui-rate-limits.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_public_release_views.py tests/test_accessibility_templates.py -q
C:\Users\blind\.local\bin\uv.exe run ruff check releasewatch/views.py releasewatch/urls.py tests/test_public_release_views.py
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-ui-rate-limits.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: tests pass and Ruff passes.

- [ ] **Step 7: Commit checkpoint**

```powershell
git add releasewatch/views.py releasewatch/urls.py templates/releasewatch tests/test_public_release_views.py tests/test_accessibility_templates.py
git commit -m "feat: add public release pages"
```

---

## Task 4: Authenticated Dashboard and Follows

**Files:**

- Modify: `releasewatch/views.py`
- Modify: `releasewatch/urls.py`
- Create: `templates/releasewatch/dashboard.html`
- Create: `templates/releasewatch/follow_list.html`
- Create: `tests/test_dashboard_follow_views.py`

- [ ] **Step 1: Write failing dashboard/follow tests**

Create `tests/test_dashboard_follow_views.py`:

```python
from datetime import date
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from releasewatch.models import Artist, DatePrecision, Follow, ReleaseEvent, ReleaseGroup

pytestmark = pytest.mark.django_db


def create_user(username="listener"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="test-password",
    )


def create_artist(name="Fugazi"):
    return Artist.objects.create(mbid=uuid4(), name=name, sort_name=name)


def create_event(artist):
    group = ReleaseGroup.objects.create(mbid=uuid4(), artist=artist, title="Repeater")
    return ReleaseEvent.objects.create(
        release_group=group,
        event_date=date(2026, 6, 22),
        date_precision=DatePrecision.DAY,
        visible=True,
    )


def test_dashboard_requires_login(client):
    response = client.get(reverse("releasewatch:dashboard"))

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_dashboard_shows_user_follows_and_release_events(client):
    user = create_user()
    other_user = create_user("other")
    followed = create_artist()
    other_artist = create_artist("Other")
    Follow.objects.create(user=user, artist=followed)
    Follow.objects.create(user=other_user, artist=other_artist)
    create_event(followed)
    create_event(other_artist)
    client.force_login(user)

    response = client.get(reverse("releasewatch:dashboard"))

    assert response.status_code == 200
    assert b"Dashboard" in response.content
    assert b"Fugazi" in response.content
    assert b"Repeater" in response.content
    assert b"Other" not in response.content


def test_follow_list_requires_login(client):
    response = client.get(reverse("releasewatch:follow_list"))

    assert response.status_code == 302


def test_follow_list_shows_active_and_ignored_follows_for_user_only(client):
    user = create_user()
    other_user = create_user("other")
    active = create_artist("Active Artist")
    ignored = create_artist("Ignored Artist")
    other = create_artist("Other Artist")
    Follow.objects.create(user=user, artist=active)
    Follow.objects.create(user=user, artist=ignored, is_ignored=True)
    Follow.objects.create(user=other_user, artist=other)
    client.force_login(user)

    response = client.get(reverse("releasewatch:follow_list"))

    assert response.status_code == 200
    assert b"Active Artist" in response.content
    assert b"Ignored Artist" in response.content
    assert b"Other Artist" not in response.content
```

- [ ] **Step 2: Run red tests**

```powershell
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-ui-rate-limits.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_dashboard_follow_views.py -q
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-ui-rate-limits.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: fails because routes/views are missing.

- [ ] **Step 3: Implement dashboard and follows views**

In `releasewatch/views.py`, import:

```python
from django.contrib.auth.decorators import login_required

from releasewatch.models import Follow
```

Add:

```python
@login_required
def dashboard(request):
    follows = (
        Follow.objects.select_related("artist")
        .filter(user=request.user, is_ignored=False)
        .order_by("artist__sort_name", "artist__name")
    )
    events = visible_release_events().filter(release_group__artist__follow__user=request.user)[:20]
    return render(request, "releasewatch/dashboard.html", {"follows": follows, "events": events})


@login_required
def follow_list(request):
    follows = (
        Follow.objects.select_related("artist")
        .filter(user=request.user)
        .order_by("is_ignored", "artist__sort_name", "artist__name")
    )
    return render(request, "releasewatch/follow_list.html", {"follows": follows})
```

- [ ] **Step 4: Add authenticated routes**

In `releasewatch/urls.py`:

```python
path("dashboard/", views.dashboard, name="dashboard"),
path("follows/", views.follow_list, name="follow_list"),
```

Update `templates/base.html` nav block so authenticated users see the routes added in this task:

```html
          {% block authenticated_nav %}
            {% if request.user.is_authenticated %}
              <li><a href="{% url 'releasewatch:dashboard' %}">Dashboard</a></li>
              <li><a href="{% url 'releasewatch:follow_list' %}">Follows</a></li>
            {% endif %}
          {% endblock %}
```

- [ ] **Step 5: Add templates**

Create `templates/releasewatch/dashboard.html`:

```html
{% extends "base.html" %}

{% block title %}Dashboard{% endblock %}

{% block content %}
  <h1>Dashboard</h1>

  <h2>Followed artists</h2>
  {% if follows %}
    <ul>
      {% for follow in follows %}
        <li><a href="{% url 'releasewatch:artist_detail' follow.artist_id %}">{{ follow.artist.name }}</a></li>
      {% endfor %}
    </ul>
  {% else %}
    <p>You are not following any artists yet.</p>
  {% endif %}

  <h2>Latest releases from followed artists</h2>
  {% include "releasewatch/includes/release_event_table.html" with events=events caption="Visible release events from followed artists" %}
{% endblock %}
```

Create `templates/releasewatch/follow_list.html`:

```html
{% extends "base.html" %}

{% block title %}Follows{% endblock %}

{% block content %}
  <h1>Follows</h1>
  {% if follows %}
    <table>
      <caption>Your followed and ignored artists</caption>
      <thead>
        <tr>
          <th scope="col">Artist</th>
          <th scope="col">State</th>
        </tr>
      </thead>
      <tbody>
        {% for follow in follows %}
          <tr>
            <td>{{ follow.artist.name }}</td>
            <td>{% if follow.is_ignored %}Ignored{% else %}Following{% endif %}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p>No follows found.</p>
  {% endif %}
{% endblock %}
```

- [ ] **Step 6: Run green dashboard/follow tests**

```powershell
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-ui-rate-limits.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_dashboard_follow_views.py tests/test_accessibility_templates.py -q
C:\Users\blind\.local\bin\uv.exe run ruff check releasewatch/views.py releasewatch/urls.py tests/test_dashboard_follow_views.py
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-ui-rate-limits.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: tests pass and Ruff passes.

- [ ] **Step 7: Commit checkpoint**

```powershell
git add releasewatch/views.py releasewatch/urls.py templates/releasewatch/dashboard.html templates/releasewatch/follow_list.html tests/test_dashboard_follow_views.py
git commit -m "feat: add dashboard and follows pages"
```

---

## Task 5: Artist Search and Follow Workflow

**Files:**

- Create or modify: `releasewatch/forms.py`
- Modify: `releasewatch/views.py`
- Modify: `releasewatch/urls.py`
- Create: `templates/releasewatch/artist_search.html`
- Create: `tests/test_artist_search_follow_views.py`

- [ ] **Step 1: Write failing search/follow tests**

Create `tests/test_artist_search_follow_views.py`:

```python
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from releasewatch.models import Artist, Follow
from releasewatch.upstreams import UpstreamArtist

pytestmark = pytest.mark.django_db


def create_user(username="listener"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="test-password",
    )


def upstream_artist(mbid, name="Fugazi"):
    return UpstreamArtist(
        mbid=str(mbid),
        name=name,
        sort_name=name,
        disambiguation="Washington, D.C. band",
        artist_type="Group",
        country="US",
        aliases=[],
        raw_payload={"id": str(mbid), "name": name},
    )


def test_artist_search_requires_login(client):
    response = client.get(reverse("releasewatch:artist_search"))

    assert response.status_code == 302


def test_artist_search_uses_musicbrainz_client_and_shows_results(client, mocker):
    user = create_user()
    mbid = uuid4()
    client.force_login(user)
    search = mocker.patch(
        "releasewatch.views.MusicBrainzClient.search_artists",
        return_value=[upstream_artist(mbid)],
    )

    response = client.get(reverse("releasewatch:artist_search"), {"q": "Fugazi"})

    assert response.status_code == 200
    search.assert_called_once()
    assert b"Fugazi" in response.content
    assert b"Follow Fugazi" in response.content


def test_artist_search_rate_limit_returns_429(client, mocker):
    user = create_user()
    client.force_login(user)
    mocker.patch(
        "releasewatch.views.check_rate_limit",
        return_value=mocker.Mock(allowed=False, retry_after_seconds=30),
    )

    response = client.get(reverse("releasewatch:artist_search"), {"q": "Fugazi"})

    assert response.status_code == 429
    assert b"Too many requests" in response.content


def test_follow_artist_creates_artist_follow_and_enqueues_sync(client, mocker):
    user = create_user()
    mbid = uuid4()
    client.force_login(user)
    lookup = mocker.patch(
        "releasewatch.views.MusicBrainzClient.lookup_artist",
        return_value=upstream_artist(mbid),
    )
    delay = mocker.patch("releasewatch.views.sync_artist_releases_task.delay")

    response = client.post(reverse("releasewatch:follow_artist"), {"mbid": str(mbid)})

    assert response.status_code == 302
    lookup.assert_called_once_with(str(mbid))
    artist = Artist.objects.get(mbid=mbid)
    follow = Follow.objects.get(user=user, artist=artist)
    assert follow.is_ignored is False
    delay.assert_called_once_with(artist.id)


def test_follow_artist_requires_post(client):
    user = create_user()
    client.force_login(user)

    response = client.get(reverse("releasewatch:follow_artist"))

    assert response.status_code == 405
```

- [ ] **Step 2: Run red tests**

```powershell
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-ui-rate-limits.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_artist_search_follow_views.py -q
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-ui-rate-limits.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: fails because routes/views/forms are missing.

- [ ] **Step 3: Add forms**

Create or extend `releasewatch/forms.py`:

```python
from django import forms

from releasewatch.models import NotificationCadence, NotificationPreference


class ArtistSearchForm(forms.Form):
    q = forms.CharField(
        label="Artist name or MusicBrainz ID",
        max_length=255,
        strip=True,
    )


class FollowArtistForm(forms.Form):
    mbid = forms.UUIDField(label="MusicBrainz artist ID")


class ImportCandidateReviewForm(forms.Form):
    action = forms.ChoiceField(
        choices=[
            ("accept", "Accept"),
            ("ignore", "Ignore"),
            ("reject", "Reject"),
        ],
        widget=forms.RadioSelect,
    )


class NotificationPreferenceForm(forms.ModelForm):
    cadence = forms.ChoiceField(
        choices=NotificationCadence.choices,
        widget=forms.RadioSelect,
    )

    class Meta:
        model = NotificationPreference
        fields = ["cadence", "email_enabled", "include_future_releases"]
```

- [ ] **Step 4: Add search and follow views**

In `releasewatch/views.py`, import:

```python
from django.contrib import messages
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect

from releasewatch.forms import ArtistSearchForm, FollowArtistForm
from releasewatch.rate_limits import (
    RateLimitUnavailable,
    check_rate_limit,
    rate_limit_unavailable_response,
    rate_limited_response,
)
from releasewatch.tasks import sync_artist_releases_task
from releasewatch.upstreams import MusicBrainzClient
```

Add helpers:

```python
def _guard_rate_limit(request, *, scope: str, rate: tuple[int, int], identity="user_or_ip"):
    limit, window_seconds = rate
    try:
        result = check_rate_limit(
            request,
            scope=scope,
            limit=limit,
            window_seconds=window_seconds,
            identity=identity,
        )
    except RateLimitUnavailable:
        return rate_limit_unavailable_response(request)
    if not result.allowed:
        return rate_limited_response(request, retry_after_seconds=result.retry_after_seconds)
    return None


def _artist_from_upstream(upstream_artist):
    artist, _ = Artist.objects.update_or_create(
        mbid=upstream_artist.mbid,
        defaults={
            "name": upstream_artist.name[:255],
            "sort_name": upstream_artist.sort_name[:255],
            "disambiguation": upstream_artist.disambiguation[:255],
            "artist_type": upstream_artist.artist_type[:64],
            "country": upstream_artist.country[:2],
            "raw_payload": upstream_artist.raw_payload,
        },
    )
    return artist
```

Add views:

```python
@login_required
def artist_search(request):
    form = ArtistSearchForm(request.GET or None)
    results = []
    if form.is_valid():
        limited_response = _guard_rate_limit(
            request,
            scope="artist-search",
            rate=settings.RATE_LIMIT_ARTIST_SEARCH_AUTHENTICATED,
        )
        if limited_response is not None:
            return limited_response
        with MusicBrainzClient() as client:
            results = client.search_artists(form.cleaned_data["q"], limit=10, offset=0)
    return render(request, "releasewatch/artist_search.html", {"form": form, "results": results})


@login_required
def follow_artist(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    limited_response = _guard_rate_limit(
        request,
        scope="follow-mutation",
        rate=settings.RATE_LIMIT_FOLLOW_MUTATION,
    )
    if limited_response is not None:
        return limited_response
    form = FollowArtistForm(request.POST)
    if not form.is_valid():
        return render(request, "releasewatch/artist_search.html", {"form": ArtistSearchForm(), "follow_form": form}, status=400)
    with MusicBrainzClient() as client:
        upstream_artist = client.lookup_artist(str(form.cleaned_data["mbid"]))
    artist = _artist_from_upstream(upstream_artist)
    Follow.objects.update_or_create(user=request.user, artist=artist, defaults={"is_ignored": False})
    sync_artist_releases_task.delay(artist.id)
    messages.success(request, f"Following {artist.name}.")
    return redirect("releasewatch:follow_list")
```

Make sure `settings` is imported from `django.conf`.

- [ ] **Step 5: Add search routes**

In `releasewatch/urls.py`:

```python
path("artists/search/", views.artist_search, name="artist_search"),
path("artists/follow/", views.follow_artist, name="follow_artist"),
```

Update `templates/base.html` authenticated nav block to include search after Dashboard:

```html
          {% block authenticated_nav %}
            {% if request.user.is_authenticated %}
              <li><a href="{% url 'releasewatch:dashboard' %}">Dashboard</a></li>
              <li><a href="{% url 'releasewatch:artist_search' %}">Search Artists</a></li>
              <li><a href="{% url 'releasewatch:follow_list' %}">Follows</a></li>
            {% endif %}
          {% endblock %}
```

- [ ] **Step 6: Add artist search template**

Create `templates/releasewatch/artist_search.html`:

```html
{% extends "base.html" %}

{% block title %}Search artists{% endblock %}

{% block content %}
  <h1>Search artists</h1>
  <form method="get" action="{% url 'releasewatch:artist_search' %}">
    <div class="field">
      {{ form.q.label_tag }}
      {{ form.q }}
      {% if form.q.errors %}
        <div id="id_q_error">{{ form.q.errors }}</div>
      {% endif %}
    </div>
    <button type="submit">Search artists</button>
  </form>

  {% if results %}
    <h2>Search results</h2>
    <ul>
      {% for artist in results %}
        <li>
          <p>
            <strong>{{ artist.name }}</strong>
            {% if artist.disambiguation %}{{ artist.disambiguation }}{% endif %}
            {% if artist.country %}{{ artist.country }}{% endif %}
            {% if artist.artist_type %}{{ artist.artist_type }}{% endif %}
          </p>
          <form method="post" action="{% url 'releasewatch:follow_artist' %}">
            {% csrf_token %}
            <input type="hidden" name="mbid" value="{{ artist.mbid }}">
            <button type="submit">Follow {{ artist.name }}</button>
          </form>
        </li>
      {% endfor %}
    </ul>
  {% endif %}
{% endblock %}
```

- [ ] **Step 7: Run green search/follow tests**

```powershell
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-ui-rate-limits.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_artist_search_follow_views.py tests/test_rate_limits.py -q
C:\Users\blind\.local\bin\uv.exe run ruff check releasewatch/forms.py releasewatch/views.py releasewatch/urls.py tests/test_artist_search_follow_views.py
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-ui-rate-limits.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: tests pass and Ruff passes.

- [ ] **Step 8: Commit checkpoint**

```powershell
git add releasewatch/forms.py releasewatch/views.py releasewatch/urls.py templates/releasewatch/artist_search.html tests/test_artist_search_follow_views.py
git commit -m "feat: add artist search follow workflow"
```

---

## Task 6: Import Review Workflow

**Files:**

- Modify: `releasewatch/views.py`
- Modify: `releasewatch/urls.py`
- Modify: `releasewatch/forms.py`
- Create: `templates/releasewatch/import_list.html`
- Create: `templates/releasewatch/import_detail.html`
- Create: `tests/test_import_review_views.py`

- [ ] **Step 1: Write failing import review tests**

Create `tests/test_import_review_views.py`:

```python
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from releasewatch.models import Artist, Follow, ImportCandidate, ImportRun

pytestmark = pytest.mark.django_db


def create_user(username="listener"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="test-password",
    )


def create_run(user):
    return ImportRun.objects.create(
        user=user,
        source=ImportRun.Source.PLAIN_TEXT,
        status=ImportRun.Status.PENDING_REVIEW,
    )


def create_candidate(run, artist=None):
    return ImportCandidate.objects.create(
        import_run=run,
        artist=artist,
        source_name=artist.name if artist else "Unknown Artist",
        source_identifier=f"plain:{uuid4()}",
    )


def test_import_list_requires_login(client):
    response = client.get(reverse("releasewatch:import_list"))

    assert response.status_code == 302


def test_import_list_shows_only_current_user_runs(client):
    user = create_user()
    other = create_user("other")
    create_run(user)
    create_run(other)
    client.force_login(user)

    response = client.get(reverse("releasewatch:import_list"))

    assert response.status_code == 200
    assert response.content.count(b"Plain text") == 1


def test_import_detail_blocks_cross_user_access(client):
    user = create_user()
    other = create_user("other")
    run = create_run(other)
    client.force_login(user)

    response = client.get(reverse("releasewatch:import_detail", args=[run.id]))

    assert response.status_code == 404


def test_accept_import_candidate_creates_follow_and_marks_candidate(client, mocker):
    user = create_user()
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    run = create_run(user)
    candidate = create_candidate(run, artist)
    client.force_login(user)
    delay = mocker.patch("releasewatch.views.sync_artist_releases_task.delay")

    response = client.post(
        reverse("releasewatch:review_import_candidate", args=[candidate.id]),
        {"action": "accept"},
    )

    assert response.status_code == 302
    candidate.refresh_from_db()
    assert candidate.review_state == ImportCandidate.ReviewState.ACCEPTED
    assert Follow.objects.filter(user=user, artist=artist, is_ignored=False).exists()
    delay.assert_called_once_with(artist.id)


def test_ignore_import_candidate_marks_follow_ignored(client):
    user = create_user()
    artist = Artist.objects.create(mbid=uuid4(), name="Unwanted")
    run = create_run(user)
    candidate = create_candidate(run, artist)
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:review_import_candidate", args=[candidate.id]),
        {"action": "ignore"},
    )

    assert response.status_code == 302
    candidate.refresh_from_db()
    assert candidate.review_state == ImportCandidate.ReviewState.IGNORED
    assert Follow.objects.filter(user=user, artist=artist, is_ignored=True).exists()


def test_review_import_candidate_requires_post(client):
    user = create_user()
    run = create_run(user)
    candidate = create_candidate(run)
    client.force_login(user)

    response = client.get(reverse("releasewatch:review_import_candidate", args=[candidate.id]))

    assert response.status_code == 405
```

- [ ] **Step 2: Run red tests**

```powershell
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-ui-rate-limits.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_import_review_views.py -q
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-ui-rate-limits.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: fails because routes/views/templates are missing.

- [ ] **Step 3: Implement import views**

In `releasewatch/views.py`, import:

```python
from releasewatch.forms import ImportCandidateReviewForm
from releasewatch.imports import accept_import_candidate, ignore_import_candidate, reject_import_candidate
from releasewatch.models import ImportCandidate, ImportRun
```

Add:

```python
@login_required
def import_list(request):
    runs = ImportRun.objects.filter(user=request.user).order_by("-created_at", "-id")
    return render(request, "releasewatch/import_list.html", {"runs": runs})


@login_required
def import_detail(request, run_id: int):
    run = get_object_or_404(
        ImportRun.objects.prefetch_related("candidates__artist"),
        pk=run_id,
        user=request.user,
    )
    return render(request, "releasewatch/import_detail.html", {"run": run})


@login_required
def review_import_candidate(request, candidate_id: int):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    limited_response = _guard_rate_limit(
        request,
        scope="import-review",
        rate=settings.RATE_LIMIT_IMPORT_REVIEW,
    )
    if limited_response is not None:
        return limited_response
    candidate = get_object_or_404(
        ImportCandidate.objects.select_related("import_run", "artist"),
        pk=candidate_id,
        import_run__user=request.user,
    )
    form = ImportCandidateReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choose a review action.")
        return redirect("releasewatch:import_detail", run_id=candidate.import_run_id)
    action = form.cleaned_data["action"]
    if action == "accept":
        follow = accept_import_candidate(candidate=candidate, user=request.user)
        sync_artist_releases_task.delay(follow.artist_id)
        messages.success(request, f"Accepted {candidate.source_name}.")
    elif action == "ignore":
        ignore_import_candidate(candidate=candidate, user=request.user)
        messages.success(request, f"Ignored {candidate.source_name}.")
    else:
        reject_import_candidate(candidate=candidate, user=request.user)
        messages.success(request, f"Rejected {candidate.source_name}.")
    return redirect("releasewatch:import_detail", run_id=candidate.import_run_id)
```

- [ ] **Step 4: Add import routes**

In `releasewatch/urls.py`:

```python
path("imports/", views.import_list, name="import_list"),
path("imports/<int:run_id>/", views.import_detail, name="import_detail"),
path("imports/candidates/<int:candidate_id>/review/", views.review_import_candidate, name="review_import_candidate"),
```

Update `templates/base.html` authenticated nav block to include imports after Follows:

```html
          {% block authenticated_nav %}
            {% if request.user.is_authenticated %}
              <li><a href="{% url 'releasewatch:dashboard' %}">Dashboard</a></li>
              <li><a href="{% url 'releasewatch:artist_search' %}">Search Artists</a></li>
              <li><a href="{% url 'releasewatch:follow_list' %}">Follows</a></li>
              <li><a href="{% url 'releasewatch:import_list' %}">Imports</a></li>
            {% endif %}
          {% endblock %}
```

- [ ] **Step 5: Add import templates**

Create `templates/releasewatch/import_list.html`:

```html
{% extends "base.html" %}

{% block title %}Imports{% endblock %}

{% block content %}
  <h1>Imports</h1>
  {% if runs %}
    <table>
      <caption>Your import runs</caption>
      <thead>
        <tr>
          <th scope="col">Source</th>
          <th scope="col">Status</th>
          <th scope="col">Created</th>
        </tr>
      </thead>
      <tbody>
        {% for run in runs %}
          <tr>
            <td><a href="{% url 'releasewatch:import_detail' run.id %}">{{ run.get_source_display }}</a></td>
            <td>{{ run.get_status_display }}</td>
            <td>{{ run.created_at }}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p>No imports found.</p>
  {% endif %}
{% endblock %}
```

Create `templates/releasewatch/import_detail.html`:

```html
{% extends "base.html" %}

{% block title %}Import review{% endblock %}

{% block content %}
  <h1>Import review</h1>
  <p>Source: {{ run.get_source_display }}. Status: {{ run.get_status_display }}.</p>

  {% if run.candidates.all %}
    <table>
      <caption>Import candidates</caption>
      <thead>
        <tr>
          <th scope="col">Candidate</th>
          <th scope="col">Matched artist</th>
          <th scope="col">State</th>
          <th scope="col">Actions</th>
        </tr>
      </thead>
      <tbody>
        {% for candidate in run.candidates.all %}
          <tr>
            <td>{{ candidate.source_name }}</td>
            <td>{% if candidate.artist %}{{ candidate.artist.name }}{% else %}No match{% endif %}</td>
            <td>{{ candidate.get_review_state_display }}</td>
            <td>
              <form method="post" action="{% url 'releasewatch:review_import_candidate' candidate.id %}">
                {% csrf_token %}
                <button type="submit" name="action" value="accept">Accept {{ candidate.source_name }}</button>
                <button type="submit" name="action" value="ignore">Ignore {{ candidate.source_name }}</button>
                <button type="submit" name="action" value="reject">Reject {{ candidate.source_name }}</button>
              </form>
            </td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p>No candidates found.</p>
  {% endif %}
{% endblock %}
```

- [ ] **Step 6: Run green import review tests**

```powershell
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-ui-rate-limits.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_import_review_views.py tests/test_import_workflows.py -q
C:\Users\blind\.local\bin\uv.exe run ruff check releasewatch/forms.py releasewatch/views.py releasewatch/urls.py tests/test_import_review_views.py
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-ui-rate-limits.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: tests pass and Ruff passes.

- [ ] **Step 7: Commit checkpoint**

```powershell
git add releasewatch/forms.py releasewatch/views.py releasewatch/urls.py templates/releasewatch/import_list.html templates/releasewatch/import_detail.html tests/test_import_review_views.py
git commit -m "feat: add import review ui"
```

---

## Task 7: Notification Settings Page

**Files:**

- Modify: `releasewatch/forms.py`
- Modify: `releasewatch/views.py`
- Modify: `releasewatch/urls.py`
- Create: `templates/releasewatch/notification_settings.html`
- Create: `tests/test_notification_settings_view.py`

- [ ] **Step 1: Write failing notification settings tests**

Create `tests/test_notification_settings_view.py`:

```python
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from releasewatch.models import NotificationCadence, NotificationPreference

pytestmark = pytest.mark.django_db


def create_user(username="listener"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="test-password",
    )


def test_notification_settings_requires_login(client):
    response = client.get(reverse("releasewatch:notification_settings"))

    assert response.status_code == 302


def test_notification_settings_creates_default_preference(client):
    user = create_user()
    client.force_login(user)

    response = client.get(reverse("releasewatch:notification_settings"))

    assert response.status_code == 200
    assert b"Notification settings" in response.content
    assert NotificationPreference.objects.filter(user=user).exists()


def test_notification_settings_saves_valid_preferences(client):
    user = create_user()
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:notification_settings"),
        {
            "cadence": NotificationCadence.WEEKLY,
            "email_enabled": "on",
        },
    )

    assert response.status_code == 302
    preference = NotificationPreference.objects.get(user=user)
    assert preference.cadence == NotificationCadence.WEEKLY
    assert preference.email_enabled is True
    assert preference.include_future_releases is False


def test_notification_settings_rejects_invalid_cadence(client):
    user = create_user()
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:notification_settings"),
        {"cadence": "bad"},
    )

    assert response.status_code == 200
    assert b"Choose a valid choice" in response.content


def test_notification_settings_rate_limit_returns_429(client, mocker):
    user = create_user()
    client.force_login(user)
    mocker.patch(
        "releasewatch.views.check_rate_limit",
        return_value=mocker.Mock(allowed=False, retry_after_seconds=30),
    )

    response = client.post(
        reverse("releasewatch:notification_settings"),
        {"cadence": NotificationCadence.DAILY},
    )

    assert response.status_code == 429
```

- [ ] **Step 2: Run red tests**

```powershell
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-ui-rate-limits.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_notification_settings_view.py -q
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-ui-rate-limits.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: fails because route/view/template are missing.

- [ ] **Step 3: Implement settings view**

In `releasewatch/views.py`, import:

```python
from releasewatch.forms import NotificationPreferenceForm
from releasewatch.models import NotificationPreference
```

Add:

```python
@login_required
def notification_settings(request):
    preference, _ = NotificationPreference.objects.get_or_create(user=request.user)
    if request.method == "POST":
        limited_response = _guard_rate_limit(
            request,
            scope="notification-settings",
            rate=settings.RATE_LIMIT_NOTIFICATION_SETTINGS,
        )
        if limited_response is not None:
            return limited_response
        form = NotificationPreferenceForm(request.POST, instance=preference)
        if form.is_valid():
            form.save()
            messages.success(request, "Notification settings saved.")
            return redirect("releasewatch:notification_settings")
    else:
        form = NotificationPreferenceForm(instance=preference)
    return render(request, "releasewatch/notification_settings.html", {"form": form})
```

- [ ] **Step 4: Add route**

In `releasewatch/urls.py`:

```python
path("settings/notifications/", views.notification_settings, name="notification_settings"),
```

Update `templates/base.html` authenticated nav block to include notification settings after Imports:

```html
          {% block authenticated_nav %}
            {% if request.user.is_authenticated %}
              <li><a href="{% url 'releasewatch:dashboard' %}">Dashboard</a></li>
              <li><a href="{% url 'releasewatch:artist_search' %}">Search Artists</a></li>
              <li><a href="{% url 'releasewatch:follow_list' %}">Follows</a></li>
              <li><a href="{% url 'releasewatch:import_list' %}">Imports</a></li>
              <li><a href="{% url 'releasewatch:notification_settings' %}">Notification Settings</a></li>
            {% endif %}
          {% endblock %}
```

- [ ] **Step 5: Add template**

Create `templates/releasewatch/notification_settings.html`:

```html
{% extends "base.html" %}

{% block title %}Notification settings{% endblock %}

{% block content %}
  <h1>Notification settings</h1>

  {% if form.errors %}
    <section class="error-summary" role="alert" aria-labelledby="form-errors-title">
      <h2 id="form-errors-title">Fix these errors</h2>
      {{ form.errors }}
    </section>
  {% endif %}

  <form method="post" action="{% url 'releasewatch:notification_settings' %}">
    {% csrf_token %}
    <fieldset>
      <legend>Notification cadence</legend>
      {{ form.cadence }}
    </fieldset>

    <div class="field">
      {{ form.email_enabled }}
      {{ form.email_enabled.label_tag }}
    </div>

    <div class="field">
      {{ form.include_future_releases }}
      {{ form.include_future_releases.label_tag }}
    </div>

    <button type="submit">Save notification settings</button>
  </form>
{% endblock %}
```

- [ ] **Step 6: Run green notification settings tests**

```powershell
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-ui-rate-limits.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_notification_settings_view.py tests/test_notifications.py -q
C:\Users\blind\.local\bin\uv.exe run ruff check releasewatch/forms.py releasewatch/views.py releasewatch/urls.py tests/test_notification_settings_view.py
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-ui-rate-limits.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: tests pass and Ruff passes.

- [ ] **Step 7: Commit checkpoint**

```powershell
git add releasewatch/forms.py releasewatch/views.py releasewatch/urls.py templates/releasewatch/notification_settings.html tests/test_notification_settings_view.py
git commit -m "feat: add notification settings ui"
```

---

## Task 8: Full Accessibility, Security, Docs, and Checkpoint

**Files:**

- Modify: `docs/development.md`
- Modify: `docs/security.md`
- Modify: `docs/agent-handoff.md`
- Conditional ratchet only when coverage report earns it: `pyproject.toml`
- Conditional ratchet only when coverage report earns it: `tests/test_quality_config.py`

- [ ] **Step 1: Add final CSRF and backend-failure regression tests**

Append to `tests/test_import_review_views.py`:

```python
def test_import_review_requires_csrf_token():
    from django.test import Client

    user = create_user("csrf-user")
    run = create_run(user)
    candidate = create_candidate(run)
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:review_import_candidate", args=[candidate.id]),
        {"action": "reject"},
    )

    assert response.status_code == 403
```

Append to `tests/test_artist_search_follow_views.py`:

```python
def test_follow_artist_rate_limit_backend_failure_returns_503(client, mocker):
    from releasewatch.rate_limits import RateLimitUnavailable

    user = create_user("rate-limit-failure")
    client.force_login(user)
    mocker.patch("releasewatch.views.check_rate_limit", side_effect=RateLimitUnavailable("down"))

    response = client.post(reverse("releasewatch:follow_artist"), {"mbid": str(uuid4())})

    assert response.status_code == 503
    assert b"Service temporarily unavailable" in response.content
```

- [ ] **Step 2: Run final focused UI test set**

```powershell
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-ui-rate-limits.sqlite3'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_rate_limits.py tests/test_accessibility_templates.py tests/test_public_release_views.py tests/test_dashboard_follow_views.py tests/test_artist_search_follow_views.py tests/test_import_review_views.py tests/test_notification_settings_view.py -q
C:\Users\blind\.local\bin\uv.exe run ruff check releasewatch config tests/test_rate_limits.py tests/test_accessibility_templates.py tests/test_public_release_views.py tests/test_dashboard_follow_views.py tests/test_artist_search_follow_views.py tests/test_import_review_views.py tests/test_notification_settings_view.py
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-ui-rate-limits.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: focused UI tests pass and Ruff passes.

- [ ] **Step 3: Update docs**

In `docs/development.md`, add under "Tests and checks":

```markdown
Run UI-focused tests:

```sh
uv run pytest tests/test_rate_limits.py tests/test_accessibility_templates.py tests/test_public_release_views.py tests/test_dashboard_follow_views.py tests/test_artist_search_follow_views.py tests/test_import_review_views.py tests/test_notification_settings_view.py -q
```
```

In `docs/security.md`, add:

```markdown
Rate limits use Django's cache backend. Production deployments must use a shared Redis cache through `REDIS_URL`; local memory caches are not sufficient across multiple web workers.

Rate-limit keys must hash user-entered or sensitive values before storage.
```

In `docs/agent-handoff.md`, update:

- Current Phase: accessible UI and rate limits complete.
- Last Known Good Commit: add each checkpoint commit from this plan.
- Next Required Step: plan RSS/iCal feed token UI or email delivery, depending user choice.
- Verification Notes: replace with latest commands.

- [ ] **Step 4: Run full coverage split**

```powershell
Remove-Item Env:DEBUG,Env:DATABASE_URL,Env:PROVIDER_TOKEN_ENCRYPTION_KEY -ErrorAction SilentlyContinue
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run coverage erase
C:\Users\blind\.local\bin\uv.exe run coverage run -m pytest tests/test_settings_security.py tests/test_quality_config.py tests/test_task_config.py tests/test_upstream_base.py tests/test_musicbrainz_client.py tests/test_listenbrainz_client.py tests/test_lastfm_client.py tests/test_rate_limits.py -q
if ($LASTEXITCODE -ne 0) { Remove-Item Env:SECRET_KEY,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue; exit $LASTEXITCODE }
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-ui-rate-limits.sqlite3'
C:\Users\blind\.local\bin\uv.exe run coverage run --append -m pytest tests/test_provider_accounts.py tests/test_import_workflows.py tests/test_release_sync.py tests/test_notifications.py tests/test_release_sync_tasks.py tests/test_accessibility_templates.py tests/test_public_release_views.py tests/test_dashboard_follow_views.py tests/test_artist_search_follow_views.py tests/test_import_review_views.py tests/test_notification_settings_view.py -q
if ($LASTEXITCODE -ne 0) { Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue; Remove-Item .tmp-ui-rate-limits.sqlite3* -ErrorAction SilentlyContinue; exit $LASTEXITCODE }
C:\Users\blind\.local\bin\uv.exe run coverage run --append -m pytest tests/test_domain_models.py tests/test_dev_admin_command.py tests/test_project_smoke.py tests/test_container_files.py tests/test_ci_workflow.py -q
$exit=$LASTEXITCODE
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-ui-rate-limits.sqlite3* -ErrorAction SilentlyContinue
exit $exit
```

Expected: all tests pass.

- [ ] **Step 5: Run coverage report and ratchet if earned**

```powershell
C:\Users\blind\.local\bin\uv.exe run coverage report
```

If total coverage is above 97, update `pyproject.toml` and `tests/test_quality_config.py` to the new integer floor and run:

```powershell
C:\Users\blind\.local\bin\uv.exe run pytest tests/test_quality_config.py -q
```

If total coverage is 97, leave floor unchanged.

- [ ] **Step 6: Run quality and security checks**

```powershell
Remove-Item Env:DEBUG,Env:DATABASE_URL,Env:PROVIDER_TOKEN_ENCRYPTION_KEY -ErrorAction SilentlyContinue
$env:SECRET_KEY='ui-rate-limit-test-secret'
$env:CELERY_BROKER_URL='amqp://guest:guest@localhost:5672//'
C:\Users\blind\.local\bin\uv.exe run ruff check .
$ruffExit=$LASTEXITCODE
C:\Users\blind\.local\bin\uv.exe run bandit -c pyproject.toml -r config releasewatch
$banditExit=$LASTEXITCODE
C:\Users\blind\.local\bin\uv.exe run python manage.py check
$checkExit=$LASTEXITCODE
C:\Users\blind\.local\bin\uv.exe lock --check
$lockExit=$LASTEXITCODE
Remove-Item Env:SECRET_KEY,Env:CELERY_BROKER_URL -ErrorAction SilentlyContinue
if ($ruffExit -ne 0) { exit $ruffExit }
if ($banditExit -ne 0) { exit $banditExit }
if ($checkExit -ne 0) { exit $checkExit }
exit $lockExit
```

Expected: all pass.

- [ ] **Step 7: Run Podman smoke**

```powershell
$env:PATH='C:\Users\blind\AppData\Local\Microsoft\WinGet\Packages\Docker.DockerCompose_Microsoft.Winget.Source_8wekyb3d8bbwe;' + $env:PATH
podman compose -f compose.yml config
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
podman compose -f compose.yml up -d db broker redis
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Start-Sleep -Seconds 35
podman compose -f compose.yml run --rm web python manage.py check
$webExit=$LASTEXITCODE
podman compose -f compose.yml down -v
exit $webExit
```

Expected: Compose config renders, services become healthy, Django check passes.

- [ ] **Step 8: Commit final docs/checkpoint and tag**

```powershell
git add docs/development.md docs/security.md docs/agent-handoff.md pyproject.toml tests/test_quality_config.py tests/test_import_review_views.py tests/test_artist_search_follow_views.py
git commit -m "docs: record accessible ui checkpoint"
git tag checkpoint/accessible-ui-rate-limits
```

If `pyproject.toml`, `tests/test_quality_config.py`, or extra tests did not change, omit them from `git add`.

- [ ] **Step 9: Final status check**

```powershell
git status --short
git log --oneline -8
git tag --list "checkpoint/accessible-ui-rate-limits"
```

Expected: clean worktree, latest commit is docs checkpoint, tag exists.
