# Task infrastructure and import workflows implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add production-ready Celery task infrastructure with RabbitMQ/Redis and build tested artist import workflows for Last.fm, ListenBrainz, and plain text.

**Architecture:** Celery routes ID-only tasks through RabbitMQ. Redis is available only for shared rate gates and short locks, not as broker. Postgres remains the durable source of truth through `ProviderAccount`, `ImportRun`, `ImportCandidate`, and existing follow/artist tables.

**Tech Stack:** Python 3.14, Django 6, Celery 5.6, RabbitMQ, Redis, django-celery-beat, cryptography Fernet, PostgreSQL 18, `uv`, pytest.

---

## File structure

- Modify `pyproject.toml`: add Celery, django-celery-beat, redis, and cryptography dependencies.
- Modify `uv.lock`: lock new dependencies.
- Create `config/celery.py`: Celery app factory/config loaded from Django settings.
- Modify `config/__init__.py`: expose Celery app.
- Modify `config/settings.py`: Celery/RabbitMQ/Redis/provider-token settings.
- Modify `compose.yml`: add RabbitMQ, Redis, dedicated workers, and beat.
- Modify `tests/test_quality_config.py`: assert dependency and coverage floor.
- Modify `tests/test_container_files.py`: assert new services and worker commands.
- Create `tests/test_task_config.py`: Celery app/config tests.
- Modify `releasewatch/models.py`: add `ProviderAccount`.
- Create migration for `ProviderAccount` and django-celery-beat dependency.
- Modify `releasewatch/admin.py`: register `ProviderAccount` without token exposure.
- Create `releasewatch/provider_tokens.py`: token encryption/decryption and redaction helpers.
- Create `tests/test_provider_accounts.py`: model, admin, and encryption tests.
- Create `releasewatch/imports.py`: import service functions, matching, candidate review.
- Create `releasewatch/tasks.py`: Celery task wrappers and due-account scanner.
- Create `tests/test_import_workflows.py`: import service/task tests.
- Modify `docs/development.md`: Celery/RabbitMQ/Redis local commands.
- Modify `docs/security.md`: provider token handling.
- Modify `docs/agent-handoff.md`: checkpoint state and next step.

## Task 1: Add dependencies and settings

**Files:**

- Modify: `tests/test_quality_config.py`
- Modify: `tests/test_settings_security.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `config/settings.py`

- [ ] **Step 1: Write failing dependency and settings tests**

Append to `tests/test_quality_config.py`:

```python


def test_task_infrastructure_dependencies_are_locked():
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dependencies = config["project"]["dependencies"]

    assert "celery>=5.6,<6.0" in dependencies
    assert "django-celery-beat>=2.9,<3.0" in dependencies
    assert "redis>=8.0,<9.0" in dependencies
    assert "cryptography>=49.0,<50.0" in dependencies
```

Append to `tests/test_settings_security.py`:

```python


def test_task_infrastructure_settings_have_production_defaults(settings):
    assert settings.CELERY_BROKER_URL.startswith("amqp://")
    assert settings.CELERY_TASK_IGNORE_RESULT is True
    assert settings.CELERY_TASK_DEFAULT_QUEUE == "maintenance"
    assert settings.CELERY_TASK_SERIALIZER == "json"
    assert settings.CELERY_ACCEPT_CONTENT == ["json"]
    assert settings.REDIS_URL.startswith("redis://")
    assert settings.PROVIDER_TOKEN_ENCRYPTION_KEY == ""
```

- [ ] **Step 2: Run red tests**

```powershell
$env:SECRET_KEY='task-import-test-secret'
uv run pytest tests/test_quality_config.py::test_task_infrastructure_dependencies_are_locked tests/test_settings_security.py::test_task_infrastructure_settings_have_production_defaults -q
Remove-Item Env:SECRET_KEY -ErrorAction SilentlyContinue
```

Expected: dependency test fails because dependencies are missing; settings test fails because settings are missing.

- [ ] **Step 3: Add dependencies**

In `pyproject.toml`, add to `[project].dependencies`:

```toml
    "celery>=5.6,<6.0",
    "cryptography>=49.0,<50.0",
    "django-celery-beat>=2.9,<3.0",
    "redis>=8.0,<9.0",
```

The exact latest compatible versions observed before writing this plan were:

- `celery==5.6.3`
- `django-celery-beat==2.9.0`
- `redis==8.0.0`
- `cryptography==49.0.0`

- [ ] **Step 4: Add Django settings**

In `config/settings.py`, add `django_celery_beat` to `INSTALLED_APPS` after `django.contrib.staticfiles`:

```python
    "django_celery_beat",
```

Add below upstream settings:

```python
CELERY_BROKER_URL = os.environ.get(
    "CELERY_BROKER_URL",
    "amqp://guest:guest@localhost:5672//",
)
CELERY_TASK_DEFAULT_QUEUE = "maintenance"
CELERY_TASK_IGNORE_RESULT = True
CELERY_RESULT_BACKEND = None
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "UTC"
CELERY_TASK_ROUTES = {
    "releasewatch.tasks.run_import": {"queue": "imports"},
    "releasewatch.tasks.import_provider_account": {"queue": "imports"},
    "releasewatch.tasks.enqueue_due_provider_imports": {"queue": "maintenance"},
}
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
PROVIDER_TOKEN_ENCRYPTION_KEY = os.environ.get("PROVIDER_TOKEN_ENCRYPTION_KEY", "")
```

- [ ] **Step 5: Lock dependencies**

```powershell
uv lock
```

Expected: `uv.lock` includes Celery, django-celery-beat, redis, cryptography, and transitive dependencies.

- [ ] **Step 6: Run green tests**

```powershell
$env:SECRET_KEY='task-import-test-secret'
uv run pytest tests/test_quality_config.py::test_task_infrastructure_dependencies_are_locked tests/test_settings_security.py::test_task_infrastructure_settings_have_production_defaults -q
uv run ruff check config tests/test_quality_config.py tests/test_settings_security.py
Remove-Item Env:SECRET_KEY -ErrorAction SilentlyContinue
```

Expected: tests pass and Ruff passes.

- [ ] **Step 7: Commit checkpoint**

```powershell
git add pyproject.toml uv.lock config/settings.py tests/test_quality_config.py tests/test_settings_security.py
git commit -m "chore: add task infrastructure settings"
```

## Task 2: Add Celery app and compose runtime

**Files:**

- Create: `config/celery.py`
- Modify: `config/__init__.py`
- Modify: `compose.yml`
- Modify: `tests/test_task_config.py`
- Modify: `tests/test_container_files.py`

- [ ] **Step 1: Write failing Celery app tests**

Create `tests/test_task_config.py`:

```python
from config.celery import app


def test_celery_app_loads_django_settings():
    assert app.main == "config"
    assert app.conf.broker_url.startswith("amqp://")
    assert app.conf.task_ignore_result is True
    assert app.conf.task_default_queue == "maintenance"


def test_celery_routes_import_tasks_to_expected_queues():
    routes = app.conf.task_routes

    assert routes["releasewatch.tasks.run_import"]["queue"] == "imports"
    assert routes["releasewatch.tasks.import_provider_account"]["queue"] == "imports"
    assert routes["releasewatch.tasks.enqueue_due_provider_imports"]["queue"] == "maintenance"


def test_celery_uses_json_serialization_only():
    assert app.conf.task_serializer == "json"
    assert app.conf.accept_content == ["json"]
```

Append to `tests/test_container_files.py`:

```python


def test_compose_defines_rabbitmq_redis_dedicated_workers_and_beat():
    compose = read_project_file("compose.yml")

    for service in (
        "broker",
        "redis",
        "worker-imports",
        "worker-sync",
        "worker-notifications",
        "worker-maintenance",
        "beat",
    ):
        assert f"  {service}:" in compose

    assert "rabbitmq:4-management" in compose
    assert "redis:8" in compose
    assert "CELERY_BROKER_URL=amqp://muspy:muspy@broker:5672//" in compose
    assert "REDIS_URL=redis://redis:6379/0" in compose
    assert "celery" in compose
    assert "-Q" in compose
    assert "imports" in compose
    assert "sync" in compose
    assert "notifications" in compose
    assert "maintenance" in compose
```

Update `test_compose_defines_database_and_django_services` to expect new services:

```python
    for service in ("web", "worker-imports", "worker-sync", "worker-notifications", "worker-maintenance", "beat"):
        assert f"  {service}:" in compose
        assert "build:" in compose
        assert "context: ." in compose
        assert "dockerfile: Containerfile" in compose
```

Replace `test_compose_runtime_commands_do_not_use_uv_run` with:

```python
def test_compose_runtime_commands_do_not_use_uv_run():
    compose = read_project_file("compose.yml")

    for service in (
        "web",
        "worker-imports",
        "worker-sync",
        "worker-notifications",
        "worker-maintenance",
        "beat",
    ):
        match = re.search(
            rf"^  {service}:\n(?P<block>(?:    .*\n?)+)",
            compose,
            re.MULTILINE,
        )
        assert match is not None
        service_block = match.group("block")
        command_line = next(
            line for line in service_block.splitlines() if "command:" in line
        )
        assert '"uv"' not in command_line
        assert '"run"' not in command_line

    assert '"python", "manage.py"' in compose
    assert '"celery", "-A", "config", "worker"' in compose
    assert '"celery", "-A", "config", "beat"' in compose
```

- [ ] **Step 2: Run red tests**

```powershell
$env:SECRET_KEY='task-import-test-secret'
uv run pytest tests/test_task_config.py tests/test_container_files.py::test_compose_defines_rabbitmq_redis_dedicated_workers_and_beat -q
Remove-Item Env:SECRET_KEY -ErrorAction SilentlyContinue
```

Expected: import failure for `config.celery` and compose assertion failure.

- [ ] **Step 3: Add Celery app**

Create `config/celery.py`:

```python
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
```

Replace `config/__init__.py` with:

```python
from .celery import app as celery_app

__all__ = ("celery_app",)
```

- [ ] **Step 4: Update Compose**

Replace `compose.yml` service section with RabbitMQ, Redis, dedicated workers, and beat:

```yaml
x-podman:
  description: "Podman Compose compatible; no Docker-specific extensions required."

x-app: &app
  build:
    context: .
    dockerfile: Containerfile
  environment:
    - DATABASE_URL=postgresql://muspy:muspy@db:5432/muspy
    - CELERY_BROKER_URL=amqp://muspy:muspy@broker:5672//
    - REDIS_URL=redis://redis:6379/0
    - DEBUG=1
    - SECRET_KEY=dev-only-change-me
    - ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0
  depends_on:
    db:
      condition: service_healthy
    broker:
      condition: service_healthy
    redis:
      condition: service_healthy

services:
  db:
    image: postgres:18
    environment:
      POSTGRES_DB: muspy
      POSTGRES_USER: muspy
      POSTGRES_PASSWORD: muspy
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U muspy -d muspy"]
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 10s
    volumes:
      - muspy-postgres-data:/var/lib/postgresql

  broker:
    image: rabbitmq:4-management
    environment:
      RABBITMQ_DEFAULT_USER: muspy
      RABBITMQ_DEFAULT_PASS: muspy
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
      interval: 10s
      timeout: 5s
      retries: 12
      start_period: 20s
    volumes:
      - muspy-rabbitmq-data:/var/lib/rabbitmq

  redis:
    image: redis:8
    command: ["redis-server", "--appendonly", "yes"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 5s
    volumes:
      - muspy-redis-data:/data

  web:
    <<: *app
    command: ["python", "manage.py", "runserver", "0.0.0.0:8000"]
    ports:
      - "8000:8000"

  worker-imports:
    <<: *app
    command: ["celery", "-A", "config", "worker", "-Q", "imports", "--loglevel=info"]

  worker-sync:
    <<: *app
    command: ["celery", "-A", "config", "worker", "-Q", "sync", "--loglevel=info"]

  worker-notifications:
    <<: *app
    command: ["celery", "-A", "config", "worker", "-Q", "notifications", "--loglevel=info"]

  worker-maintenance:
    <<: *app
    command: ["celery", "-A", "config", "worker", "-Q", "maintenance", "--loglevel=info"]

  beat:
    <<: *app
    command: ["celery", "-A", "config", "beat", "--loglevel=info"]

volumes:
  muspy-postgres-data:
  muspy-rabbitmq-data:
  muspy-redis-data:
```

- [ ] **Step 5: Run green tests**

```powershell
$env:SECRET_KEY='task-import-test-secret'
uv run pytest tests/test_task_config.py tests/test_container_files.py -q
uv run ruff check config tests/test_task_config.py tests/test_container_files.py
Remove-Item Env:SECRET_KEY -ErrorAction SilentlyContinue
```

Expected: tests pass and Ruff passes.

- [ ] **Step 6: Validate Compose with Podman**

```powershell
$composeDir='C:\Users\blind\AppData\Local\Microsoft\WinGet\Packages\Docker.DockerCompose_Microsoft.Winget.Source_8wekyb3d8bbwe'
$env:Path="$composeDir;$env:Path"
podman compose -f compose.yml config
```

Expected: config renders `broker`, `redis`, dedicated workers, and beat without error.

- [ ] **Step 7: Commit checkpoint**

```powershell
git add config/celery.py config/__init__.py compose.yml tests/test_task_config.py tests/test_container_files.py
git commit -m "chore: add celery runtime wiring"
```

## Task 3: Add provider account model and admin

**Files:**

- Modify: `releasewatch/models.py`
- Modify: `releasewatch/admin.py`
- Create migration: `releasewatch/migrations/0005_provider_accounts.py`
- Create: `tests/test_provider_accounts.py`

- [ ] **Step 1: Write failing provider account model/admin tests**

Create `tests/test_provider_accounts.py`:

```python
import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from releasewatch.models import ProviderAccount


def create_user(username="provider-user"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="test-pass-123",
    )


@pytest.mark.django_db
def test_provider_account_stores_recurring_import_identity_without_token():
    user = create_user()

    account = ProviderAccount.objects.create(
        user=user,
        provider=ProviderAccount.Provider.LASTFM,
        external_username="listener",
    )

    assert account.status == ProviderAccount.Status.ACTIVE
    assert account.token_encrypted == ""
    assert account.scopes == []
    assert str(account) == "lastfm:listener"


@pytest.mark.django_db
def test_provider_account_is_unique_per_user_provider_and_username():
    user = create_user()
    ProviderAccount.objects.create(
        user=user,
        provider=ProviderAccount.Provider.LISTENBRAINZ,
        external_username="listener",
    )

    with pytest.raises(IntegrityError):
        ProviderAccount.objects.create(
            user=user,
            provider=ProviderAccount.Provider.LISTENBRAINZ,
            external_username="listener",
        )


@pytest.mark.django_db
def test_revoked_provider_account_allows_reconnect_with_same_username():
    user = create_user("reconnect-user")
    ProviderAccount.objects.create(
        user=user,
        provider=ProviderAccount.Provider.LISTENBRAINZ,
        external_username="listener",
        status=ProviderAccount.Status.REVOKED,
    )

    active = ProviderAccount.objects.create(
        user=user,
        provider=ProviderAccount.Provider.LISTENBRAINZ,
        external_username="listener",
    )

    assert active.status == ProviderAccount.Status.ACTIVE


def test_provider_account_is_registered_without_token_search():
    import releasewatch.admin  # noqa: F401

    model_admin = admin.site._registry[ProviderAccount]

    assert "token_encrypted" not in model_admin.search_fields
    assert "token_encrypted" not in model_admin.list_display
```

- [ ] **Step 2: Run red tests**

```powershell
$env:SECRET_KEY='task-import-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-provider.sqlite3'
uv run pytest tests/test_provider_accounts.py -q
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-provider.sqlite3* -ErrorAction SilentlyContinue
```

Expected: import failure for `ProviderAccount`.

- [ ] **Step 3: Add model**

In `releasewatch/models.py`, add after `ImportCandidate`:

```python
class ProviderAccount(models.Model):
    class Provider(models.TextChoices):
        LASTFM = "lastfm", "Last.fm"
        LISTENBRAINZ = "listenbrainz", "ListenBrainz"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    provider = models.CharField(max_length=32, choices=Provider)
    external_username = models.CharField(max_length=255)
    token_encrypted = models.TextField(blank=True)
    scopes = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.ACTIVE)
    last_imported_at = models.DateTimeField(null=True, blank=True)
    last_error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "provider"]),
            models.Index(fields=["provider", "status"]),
            models.Index(fields=["last_imported_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "provider", "external_username"],
                condition=models.Q(status=Status.ACTIVE),
                name="provider_account_unique_user_provider_username",
            )
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.external_username}"
```

- [ ] **Step 4: Register admin**

In `releasewatch/admin.py`, add `ProviderAccount` to imports and register:

```python
@admin.register(ProviderAccount)
class ProviderAccountAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "provider",
        "external_username",
        "status",
        "last_imported_at",
        "updated_at",
    ]
    list_filter = ["provider", "status"]
    search_fields = ["user__username", "user__email", "external_username"]
```

- [ ] **Step 5: Generate migration**

```powershell
$env:DEBUG='1'
$env:SECRET_KEY='task-import-test-secret'
uv run python manage.py makemigrations releasewatch --name provider_accounts
Remove-Item Env:DEBUG,Env:SECRET_KEY -ErrorAction SilentlyContinue
```

Expected: creates `releasewatch/migrations/0005_provider_accounts.py`.

- [ ] **Step 6: Run green tests**

```powershell
$env:SECRET_KEY='task-import-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-provider.sqlite3'
uv run pytest tests/test_provider_accounts.py -q
uv run python manage.py makemigrations --check --dry-run
uv run ruff check releasewatch tests/test_provider_accounts.py
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-provider.sqlite3* -ErrorAction SilentlyContinue
```

Expected: provider tests pass, no migration drift, Ruff passes.

- [ ] **Step 7: Commit checkpoint**

```powershell
git add releasewatch/models.py releasewatch/admin.py releasewatch/migrations/0005_provider_accounts.py tests/test_provider_accounts.py
git commit -m "feat: add provider account model"
```

## Task 4: Add token encryption helpers

**Files:**

- Create: `releasewatch/provider_tokens.py`
- Modify: `tests/test_provider_accounts.py`

- [ ] **Step 1: Write failing token encryption tests**

Append to `tests/test_provider_accounts.py`:

```python
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from releasewatch.provider_tokens import (
    decrypt_provider_token,
    encrypt_provider_token,
    redact_provider_secrets,
)


@override_settings(PROVIDER_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode())
def test_provider_token_round_trips_without_plaintext_storage():
    encrypted = encrypt_provider_token("listenbrainz-token")

    assert encrypted != "listenbrainz-token"
    assert "listenbrainz-token" not in encrypted
    assert decrypt_provider_token(encrypted) == "listenbrainz-token"


@override_settings(PROVIDER_TOKEN_ENCRYPTION_KEY="")
def test_encrypt_provider_token_requires_key():
    with pytest.raises(ImproperlyConfigured):
        encrypt_provider_token("listenbrainz-token")


def test_redact_provider_secrets_removes_nested_values():
    payload = {
        "token": "listenbrainz-token",
        "nested": ["api-key", {"secret": "lastfm-secret"}],
    }

    redacted = redact_provider_secrets(
        payload,
        secret_values=["listenbrainz-token", "api-key", "lastfm-secret"],
    )

    assert "listenbrainz-token" not in str(redacted)
    assert "api-key" not in str(redacted)
    assert "lastfm-secret" not in str(redacted)
```

- [ ] **Step 2: Run red tests**

```powershell
$env:SECRET_KEY='task-import-test-secret'
uv run pytest tests/test_provider_accounts.py::test_provider_token_round_trips_without_plaintext_storage tests/test_provider_accounts.py::test_encrypt_provider_token_requires_key tests/test_provider_accounts.py::test_redact_provider_secrets_removes_nested_values -q
Remove-Item Env:SECRET_KEY -ErrorAction SilentlyContinue
```

Expected: import failure for `releasewatch.provider_tokens`.

- [ ] **Step 3: Implement helper**

Create `releasewatch/provider_tokens.py`:

```python
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class ProviderTokenError(ValueError):
    pass


def encrypt_provider_token(token: str) -> str:
    if not token:
        return ""
    return _fernet().encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_provider_token(token_encrypted: str) -> str:
    if not token_encrypted:
        return ""
    try:
        return _fernet().decrypt(token_encrypted.encode("ascii")).decode("utf-8")
    except InvalidToken as error:
        raise ProviderTokenError("Provider token could not be decrypted.") from error


def redact_provider_secrets(payload: Any, *, secret_values: list[str]) -> Any:
    redacted = payload
    for value in secret_values:
        if value:
            redacted = _redact_string(redacted, value)
    return redacted


def _fernet() -> Fernet:
    key = settings.PROVIDER_TOKEN_ENCRYPTION_KEY
    if not key:
        raise ImproperlyConfigured("PROVIDER_TOKEN_ENCRYPTION_KEY must be set to store provider tokens.")
    return Fernet(key.encode("ascii"))


def _redact_string(payload: Any, value: str) -> Any:
    if isinstance(payload, dict):
        return {key: _redact_string(child, value) for key, child in payload.items()}
    if isinstance(payload, list):
        return [_redact_string(item, value) for item in payload]
    if isinstance(payload, str):
        return payload.replace(value, "[redacted]")
    return payload
```

- [ ] **Step 4: Run green tests**

```powershell
$env:SECRET_KEY='task-import-test-secret'
uv run pytest tests/test_provider_accounts.py -q
uv run ruff check releasewatch/provider_tokens.py tests/test_provider_accounts.py
Remove-Item Env:SECRET_KEY -ErrorAction SilentlyContinue
```

Expected: token tests and model tests pass; Ruff passes.

- [ ] **Step 5: Commit checkpoint**

```powershell
git add releasewatch/provider_tokens.py tests/test_provider_accounts.py
git commit -m "feat: add provider token encryption"
```

## Task 5: Add import service for plain text and review actions

**Files:**

- Create: `releasewatch/imports.py`
- Create: `tests/test_import_workflows.py`

- [ ] **Step 1: Write failing plain text and review tests**

Create `tests/test_import_workflows.py`:

```python
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from releasewatch.imports import (
    accept_import_candidate,
    ignore_import_candidate,
    start_plain_text_import,
)
from releasewatch.models import Artist, Follow, ImportCandidate, ImportRun


def create_user(username="import-user"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="test-pass-123",
    )


@pytest.mark.django_db
def test_plain_text_import_creates_candidates_without_duplicates():
    user = create_user()

    run = start_plain_text_import(user=user, text="Fugazi\n\nFugazi\nUnwound")

    assert run.source == ImportRun.Source.PLAIN_TEXT
    assert run.status == ImportRun.Status.PENDING_REVIEW
    assert list(run.candidates.order_by("source_name").values_list("source_name", flat=True)) == [
        "Fugazi",
        "Unwound",
    ]


@pytest.mark.django_db
def test_accept_import_candidate_creates_follow_once():
    user = create_user()
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    run = ImportRun.objects.create(user=user, source=ImportRun.Source.PLAIN_TEXT)
    candidate = ImportCandidate.objects.create(
        import_run=run,
        artist=artist,
        source_name="Fugazi",
    )

    accept_import_candidate(candidate=candidate, user=user)
    accept_import_candidate(candidate=candidate, user=user)

    assert Follow.objects.filter(user=user, artist=artist, is_ignored=False).count() == 1
    candidate.refresh_from_db()
    assert candidate.review_state == ImportCandidate.ReviewState.ACCEPTED


@pytest.mark.django_db
def test_ignore_import_candidate_marks_candidate_and_follow_ignored():
    user = create_user()
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    run = ImportRun.objects.create(user=user, source=ImportRun.Source.PLAIN_TEXT)
    candidate = ImportCandidate.objects.create(
        import_run=run,
        artist=artist,
        source_name="Fugazi",
    )

    ignore_import_candidate(candidate=candidate, user=user)

    assert Follow.objects.get(user=user, artist=artist).is_ignored is True
    candidate.refresh_from_db()
    assert candidate.review_state == ImportCandidate.ReviewState.IGNORED
```

- [ ] **Step 2: Run red tests**

```powershell
$env:SECRET_KEY='task-import-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-import.sqlite3'
uv run pytest tests/test_import_workflows.py -q
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-import.sqlite3* -ErrorAction SilentlyContinue
```

Expected: import failure for `releasewatch.imports`.

- [ ] **Step 3: Implement service**

Create `releasewatch/imports.py`:

```python
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from releasewatch.models import (
    Artist,
    Follow,
    ImportCandidate,
    ImportRun,
)
from releasewatch.upstreams.base import ImportedArtist


@dataclass(frozen=True)
class ImportResult:
    run: ImportRun
    created_count: int
    updated_count: int


def start_plain_text_import(*, user, text: str) -> ImportRun:
    names = _plain_text_names(text)
    run = ImportRun.objects.create(
        user=user,
        source=ImportRun.Source.PLAIN_TEXT,
        status=ImportRun.Status.STARTED,
        raw_payload={"line_count": len(text.splitlines())},
    )
    imported = [
        ImportedArtist(
            source_name=name,
            source_identifier=f"plain:{name.casefold()}",
            mbid="",
            raw_payload={"name": name},
        )
        for name in names
    ]
    apply_imported_artists(run=run, imported_artists=imported)
    return run


def apply_imported_artists(*, run: ImportRun, imported_artists: Iterable[ImportedArtist]) -> ImportResult:
    created_count = 0
    updated_count = 0
    with transaction.atomic():
        locked_run = ImportRun.objects.select_for_update().get(pk=run.pk)
        for imported_artist in imported_artists:
            artist = _artist_for_imported(imported_artist)
            _, created = ImportCandidate.objects.update_or_create(
                import_run=locked_run,
                source_identifier=imported_artist.source_identifier,
                defaults={
                    "artist": artist,
                    "source_name": imported_artist.source_name,
                    "raw_payload": imported_artist.raw_payload,
                },
            )
            if created:
                created_count += 1
            else:
                updated_count += 1
        locked_run.status = ImportRun.Status.PENDING_REVIEW
        locked_run.error_message = ""
        locked_run.save(update_fields=["status", "error_message", "updated_at"])
    run.refresh_from_db()
    return ImportResult(run=run, created_count=created_count, updated_count=updated_count)


def mark_import_failed(*, run: ImportRun, message: str) -> None:
    run.status = ImportRun.Status.FAILED
    run.error_message = message
    run.save(update_fields=["status", "error_message", "updated_at"])


def accept_import_candidate(*, candidate: ImportCandidate, user) -> Follow:
    _ensure_candidate_owner(candidate=candidate, user=user)
    if candidate.artist is None:
        raise ValueError("Import candidate has no matched artist.")
    follow, _ = Follow.objects.update_or_create(
        user=user,
        artist=candidate.artist,
        defaults={"is_ignored": False},
    )
    candidate.review_state = ImportCandidate.ReviewState.ACCEPTED
    candidate.reviewed_at = timezone.now()
    candidate.save(update_fields=["review_state", "reviewed_at"])
    return follow


def ignore_import_candidate(*, candidate: ImportCandidate, user) -> Follow | None:
    _ensure_candidate_owner(candidate=candidate, user=user)
    follow = None
    if candidate.artist is not None:
        follow, _ = Follow.objects.update_or_create(
            user=user,
            artist=candidate.artist,
            defaults={"is_ignored": True},
        )
    candidate.review_state = ImportCandidate.ReviewState.IGNORED
    candidate.reviewed_at = timezone.now()
    candidate.save(update_fields=["review_state", "reviewed_at"])
    return follow


def _artist_for_imported(imported_artist: ImportedArtist) -> Artist | None:
    if not imported_artist.mbid:
        return None
    artist, _ = Artist.objects.update_or_create(
        mbid=UUID(imported_artist.mbid),
        defaults={
            "name": imported_artist.source_name,
            "raw_payload": imported_artist.raw_payload,
        },
    )
    return artist


def _plain_text_names(text: str) -> list[str]:
    seen = set()
    names = []
    for line in text.splitlines():
        name = " ".join(line.strip().split())
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _ensure_candidate_owner(*, candidate: ImportCandidate, user) -> None:
    if candidate.import_run.user_id != user.id:
        raise PermissionError("Import candidate does not belong to user.")
```

- [ ] **Step 4: Run green tests**

```powershell
$env:SECRET_KEY='task-import-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-import.sqlite3'
uv run pytest tests/test_import_workflows.py -q
uv run ruff check releasewatch/imports.py tests/test_import_workflows.py
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-import.sqlite3* -ErrorAction SilentlyContinue
```

Expected: tests pass and Ruff passes.

- [ ] **Step 5: Commit checkpoint**

```powershell
git add releasewatch/imports.py tests/test_import_workflows.py
git commit -m "feat: add import candidate services"
```

## Task 6: Add provider import services

**Files:**

- Modify: `releasewatch/imports.py`
- Modify: `tests/test_import_workflows.py`

- [ ] **Step 1: Write failing provider import tests**

Append to `tests/test_import_workflows.py`:

```python
from releasewatch.models import ProviderAccount
from releasewatch.upstreams.base import ImportedArtist


class FakeLastFmClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get_user_top_artists(self, username, *, limit=100, page=1):
        self.calls.append((username, limit, page))
        return self.rows


class FakeListenBrainzClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get_user_artists(self, username, token, *, count=100, offset=0):
        self.calls.append((username, token, count, offset))
        return self.rows


@pytest.mark.django_db
def test_lastfm_import_uses_username_and_server_key_without_storing_credentials():
    user = create_user("lastfm-user")
    client = FakeLastFmClient(
        [
            ImportedArtist(
                source_name="Fugazi",
                source_identifier="lastfm:fugazi",
                mbid="",
                raw_payload={"name": "Fugazi"},
            )
        ]
    )

    from releasewatch.imports import start_lastfm_import

    run = start_lastfm_import(user=user, username="listener", client=client)

    assert run.source == ImportRun.Source.LASTFM
    assert client.calls == [("listener", 100, 1)]
    assert run.candidates.get().source_name == "Fugazi"


@pytest.mark.django_db
def test_listenbrainz_one_shot_import_does_not_persist_token():
    user = create_user("listenbrainz-user")
    client = FakeListenBrainzClient(
        [
            ImportedArtist(
                source_name="Unwound",
                source_identifier="listenbrainz:unwound",
                mbid="",
                raw_payload={"artist_name": "Unwound"},
            )
        ]
    )

    from releasewatch.imports import start_listenbrainz_import

    run = start_listenbrainz_import(
        user=user,
        username="listener",
        token="private-token",
        client=client,
        persist_token=False,
    )

    assert run.source == ImportRun.Source.LISTENBRAINZ
    assert client.calls == [("listener", "private-token", 100, 0)]
    assert ProviderAccount.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_listenbrainz_recurring_import_stores_encrypted_token(settings):
    from cryptography.fernet import Fernet

    from releasewatch.imports import start_listenbrainz_import

    settings.PROVIDER_TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    user = create_user("recurring-listenbrainz-user")
    client = FakeListenBrainzClient([])

    start_listenbrainz_import(
        user=user,
        username="listener",
        token="private-token",
        client=client,
        persist_token=True,
    )

    account = ProviderAccount.objects.get(user=user)
    assert account.provider == ProviderAccount.Provider.LISTENBRAINZ
    assert account.external_username == "listener"
    assert account.token_encrypted
    assert "private-token" not in account.token_encrypted
```

- [ ] **Step 2: Run red tests**

```powershell
$env:SECRET_KEY='task-import-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-import.sqlite3'
uv run pytest tests/test_import_workflows.py::test_lastfm_import_uses_username_and_server_key_without_storing_credentials tests/test_import_workflows.py::test_listenbrainz_one_shot_import_does_not_persist_token tests/test_import_workflows.py::test_listenbrainz_recurring_import_stores_encrypted_token -q
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-import.sqlite3* -ErrorAction SilentlyContinue
```

Expected: import failures for provider import functions.

- [ ] **Step 3: Implement provider imports**

In `releasewatch/imports.py`, add imports:

```python
from releasewatch.models import ProviderAccount
from releasewatch.provider_tokens import encrypt_provider_token, redact_provider_secrets
from releasewatch.upstreams.lastfm import LastFmClient
from releasewatch.upstreams.listenbrainz import ListenBrainzClient
```

Add service functions:

```python
def start_lastfm_import(*, user, username: str, client: LastFmClient | None = None) -> ImportRun:
    client = client or LastFmClient()
    run = ImportRun.objects.create(
        user=user,
        source=ImportRun.Source.LASTFM,
        status=ImportRun.Status.STARTED,
        raw_payload={"username": username},
    )
    try:
        imported = client.get_user_top_artists(username, limit=100, page=1)
        apply_imported_artists(run=run, imported_artists=imported)
    except Exception as error:
        mark_import_failed(run=run, message=str(error))
        raise
    run.refresh_from_db()
    return run


def start_listenbrainz_import(
    *,
    user,
    username: str,
    token: str,
    client: ListenBrainzClient | None = None,
    persist_token: bool = False,
) -> ImportRun:
    client = client or ListenBrainzClient()
    if persist_token:
        ProviderAccount.objects.update_or_create(
            user=user,
            provider=ProviderAccount.Provider.LISTENBRAINZ,
            external_username=username,
            defaults={
                "token_encrypted": encrypt_provider_token(token),
                "status": ProviderAccount.Status.ACTIVE,
                "last_error_message": "",
            },
        )
    run = ImportRun.objects.create(
        user=user,
        source=ImportRun.Source.LISTENBRAINZ,
        status=ImportRun.Status.STARTED,
        raw_payload={"username": username},
    )
    try:
        imported = client.get_user_artists(username, token, count=100, offset=0)
        apply_imported_artists(run=run, imported_artists=imported)
    except Exception as error:
        run.raw_payload = redact_provider_secrets(run.raw_payload, secret_values=[token])
        run.save(update_fields=["raw_payload", "updated_at"])
        mark_import_failed(run=run, message=str(error).replace(token, "[redacted]"))
        raise
    run.refresh_from_db()
    return run
```

- [ ] **Step 4: Run green tests**

```powershell
$env:SECRET_KEY='task-import-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-import.sqlite3'
uv run pytest tests/test_import_workflows.py -q
uv run ruff check releasewatch/imports.py tests/test_import_workflows.py
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-import.sqlite3* -ErrorAction SilentlyContinue
```

Expected: import workflow tests pass and Ruff passes.

- [ ] **Step 5: Commit checkpoint**

```powershell
git add releasewatch/imports.py tests/test_import_workflows.py
git commit -m "feat: add provider import services"
```

## Task 7: Add Celery task wrappers and due import scanner

**Files:**

- Create: `releasewatch/tasks.py`
- Modify: `tests/test_import_workflows.py`

- [ ] **Step 1: Write failing task tests**

Append to `tests/test_import_workflows.py`:

```python
from releasewatch.tasks import enqueue_due_provider_imports, import_provider_account, run_import


@pytest.mark.django_db
def test_run_import_task_uses_import_run_id_for_plain_text():
    user = create_user("task-import-user")
    run = ImportRun.objects.create(
        user=user,
        source=ImportRun.Source.PLAIN_TEXT,
        raw_payload={"text": "Fugazi\nUnwound"},
    )

    run_import(run.id)

    run.refresh_from_db()
    assert run.status == ImportRun.Status.PENDING_REVIEW
    assert run.candidates.count() == 2


@pytest.mark.django_db
def test_import_provider_account_marks_missing_token_as_failed():
    user = create_user("provider-task-user")
    account = ProviderAccount.objects.create(
        user=user,
        provider=ProviderAccount.Provider.LISTENBRAINZ,
        external_username="listener",
    )

    import_provider_account(account.id)

    account.refresh_from_db()
    assert account.status == ProviderAccount.Status.FAILED
    assert "token" in account.last_error_message.lower()


@pytest.mark.django_db
def test_enqueue_due_provider_imports_enqueues_active_accounts(mocker):
    user = create_user("scanner-user")
    account = ProviderAccount.objects.create(
        user=user,
        provider=ProviderAccount.Provider.LASTFM,
        external_username="listener",
    )
    delay = mocker.patch("releasewatch.tasks.import_provider_account.delay")

    count = enqueue_due_provider_imports(batch_size=10)

    assert count == 1
    delay.assert_called_once_with(account.id)
```

- [ ] **Step 2: Run red tests**

```powershell
$env:SECRET_KEY='task-import-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-import.sqlite3'
uv run pytest tests/test_import_workflows.py::test_run_import_task_uses_import_run_id_for_plain_text tests/test_import_workflows.py::test_import_provider_account_marks_missing_token_as_failed tests/test_import_workflows.py::test_enqueue_due_provider_imports_enqueues_active_accounts -q
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-import.sqlite3* -ErrorAction SilentlyContinue
```

Expected: import failure for `releasewatch.tasks`.

- [ ] **Step 3: Implement task wrappers**

Create `releasewatch/tasks.py`:

```python
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from releasewatch.imports import (
    apply_imported_artists,
    mark_import_failed,
    start_lastfm_import,
    start_listenbrainz_import,
    start_plain_text_import,
)
from releasewatch.models import ImportRun, ProviderAccount
from releasewatch.provider_tokens import ProviderTokenError, decrypt_provider_token
from releasewatch.upstreams.listenbrainz import ListenBrainzClient


@shared_task(bind=True, autoretry_for=(TimeoutError,), retry_backoff=True, retry_jitter=True)
def run_import(self, import_run_id: int) -> None:
    run = ImportRun.objects.get(pk=import_run_id)
    if run.status == ImportRun.Status.PENDING_REVIEW:
        return
    if run.source == ImportRun.Source.PLAIN_TEXT:
        text = str(run.raw_payload.get("text", ""))
        imported_run = start_plain_text_import(user=run.user, text=text)
        run.candidates.all().delete()
        for candidate in imported_run.candidates.all():
            candidate.import_run = run
            candidate.pk = None
            candidate.save()
        imported_run.delete()
        run.status = ImportRun.Status.PENDING_REVIEW
        run.error_message = ""
        run.save(update_fields=["status", "error_message", "updated_at"])
        return
    mark_import_failed(run=run, message=f"Unsupported import source: {run.source}")


@shared_task(bind=True, autoretry_for=(TimeoutError,), retry_backoff=True, retry_jitter=True)
def import_provider_account(self, provider_account_id: int) -> None:
    account = ProviderAccount.objects.select_related("user").get(pk=provider_account_id)
    if account.status != ProviderAccount.Status.ACTIVE:
        return
    try:
        if account.provider == ProviderAccount.Provider.LASTFM:
            start_lastfm_import(user=account.user, username=account.external_username)
        elif account.provider == ProviderAccount.Provider.LISTENBRAINZ:
            token = decrypt_provider_token(account.token_encrypted)
            if not token:
                raise ProviderTokenError("Provider account token is missing.")
            start_listenbrainz_import(
                user=account.user,
                username=account.external_username,
                token=token,
                client=ListenBrainzClient(),
                persist_token=False,
            )
        else:
            raise ValueError(f"Unsupported provider: {account.provider}")
    except Exception as error:
        account.status = ProviderAccount.Status.FAILED
        account.last_error_message = str(error)
        account.save(update_fields=["status", "last_error_message", "updated_at"])
        return
    account.last_imported_at = timezone.now()
    account.last_error_message = ""
    account.save(update_fields=["last_imported_at", "last_error_message", "updated_at"])


@shared_task
def enqueue_due_provider_imports(batch_size: int = 100) -> int:
    with transaction.atomic():
        accounts = list(
            ProviderAccount.objects.select_for_update(skip_locked=True)
            .filter(status=ProviderAccount.Status.ACTIVE)
            .order_by("last_imported_at", "id")[:batch_size]
        )
    for account in accounts:
        import_provider_account.delay(account.id)
    return len(accounts)
```

- [ ] **Step 4: Run green tests**

```powershell
$env:SECRET_KEY='task-import-test-secret'
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-import.sqlite3'
uv run pytest tests/test_import_workflows.py -q
uv run ruff check releasewatch/tasks.py releasewatch/imports.py tests/test_import_workflows.py
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item .tmp-import.sqlite3* -ErrorAction SilentlyContinue
```

Expected: import workflow tests pass and Ruff passes.

- [ ] **Step 5: Commit checkpoint**

```powershell
git add releasewatch/tasks.py tests/test_import_workflows.py
git commit -m "feat: add import celery tasks"
```

## Task 8: Documentation and full verification

**Files:**

- Modify: `docs/development.md`
- Modify: `docs/security.md`
- Modify: `docs/agent-handoff.md`

- [ ] **Step 1: Update user-facing docs**

Add to `docs/development.md`:

````markdown
## Background workers

This project uses Celery with RabbitMQ for task routing. Redis is available for shared rate-limit state and short locks. Postgres stores durable workflow state.

Run the container stack:

```sh
podman compose -f compose.yml up db broker redis web worker-imports worker-sync worker-notifications worker-maintenance beat
```

Run a worker on bare metal:

```sh
uv run celery -A config worker -Q imports --loglevel=info
```
````

Add to `docs/security.md`:

```markdown
## Provider tokens

Provider tokens are encrypted before storage. Set `PROVIDER_TOKEN_ENCRYPTION_KEY` before enabling recurring ListenBrainz imports. Do not use `SECRET_KEY` as the provider-token key.

Celery task arguments must contain database IDs only. Do not pass provider tokens, API keys, raw payloads, or signed URLs through the broker.
```

Update `docs/agent-handoff.md`:

- current phase: task infrastructure and import workflow complete
- last known good commit: latest commit from this plan
- next required step: write release sync and notification fanout plan
- verification evidence from Step 2

- [ ] **Step 2: Run full verification**

```powershell
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
$env:SECRET_KEY='task-import-test-secret'
$env:PROVIDER_TOKEN_ENCRYPTION_KEY='set-by-tests-or-env-only'
uv run coverage erase
uv run coverage run -m pytest tests/test_settings_security.py tests/test_quality_config.py tests/test_task_config.py tests/test_upstream_base.py tests/test_musicbrainz_client.py tests/test_listenbrainz_client.py tests/test_lastfm_client.py tests/test_provider_accounts.py tests/test_import_workflows.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$env:DEBUG='1'
$env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-task-import.sqlite3'
uv run coverage run --append -m pytest tests/test_domain_models.py tests/test_dev_admin_command.py tests/test_project_smoke.py tests/test_container_files.py tests/test_ci_workflow.py -q
if ($LASTEXITCODE -ne 0) { Remove-Item .tmp-task-import.sqlite3* -ErrorAction SilentlyContinue; exit $LASTEXITCODE }
Remove-Item Env:DEBUG,Env:SECRET_KEY,Env:DATABASE_URL,Env:PROVIDER_TOKEN_ENCRYPTION_KEY -ErrorAction SilentlyContinue
uv run coverage report
uv run ruff check .
uv run bandit -c pyproject.toml -r config releasewatch
uv run python manage.py check
Remove-Item .tmp-task-import.sqlite3* -ErrorAction SilentlyContinue
```

Expected:

- tests pass
- coverage stays at or above 96%
- Ruff passes
- Bandit reports no issues
- Django check reports no issues

- [ ] **Step 3: Run Podman Compose verification**

```powershell
$composeDir='C:\Users\blind\AppData\Local\Microsoft\WinGet\Packages\Docker.DockerCompose_Microsoft.Winget.Source_8wekyb3d8bbwe'
$env:Path="$composeDir;$env:Path"
podman build -f Containerfile -t muspy:dev .
podman compose -f compose.yml config
podman compose -f compose.yml up -d db broker redis
podman compose -f compose.yml run --rm web python manage.py check
podman compose -f compose.yml run --rm worker-imports celery -A config inspect ping --destination celery@localhost
podman compose -f compose.yml down -v
```

If `inspect ping` cannot reach a worker because the run container exits after command execution, replace it with:

```powershell
podman compose -f compose.yml run --rm worker-imports celery -A config report
```

Expected: image builds, compose config renders, core services become healthy, Django check passes, and Celery can load app config.

- [ ] **Step 4: Commit final checkpoint and tag**

```powershell
git add docs/development.md docs/security.md docs/agent-handoff.md
git commit -m "docs: record task import workflow checkpoint"
git tag -f checkpoint/task-import-workflows
git status --short --branch --untracked-files=all
```

Expected: worktree clean and tag points to final checkpoint.

## Self-review checklist

- Spec coverage:
  - Celery/RabbitMQ/Redis infrastructure covered by Tasks 1-2.
  - Provider account and token encryption covered by Tasks 3-4.
  - Import services and review actions covered by Tasks 5-6.
  - Celery task wrappers and scanner covered by Task 7.
  - Docs and verification covered by Task 8.
- Release sync and notification fanout intentionally remain out of this plan and move to the next plan.
- No live provider tests are required.
- Coverage floor remains 96 and must ratchet up only when full verification exceeds it.
