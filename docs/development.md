# Development

Use this setup for the modern Muspy fork. The legacy application under
`legacy/` is kept for provenance and reference only.

## Requirements

- `uv` 0.11.23 or newer
- Python 3.14, managed by `uv`
- PostgreSQL 18, or Podman Compose or Docker Compose for a containerized
  PostgreSQL 18 database

For Windows with Podman, install Podman and a Compose provider. One working
setup is:

```powershell
choco install podman-cli
winget install --id Docker.DockerCompose --accept-source-agreements --accept-package-agreements
podman machine init
podman machine start
```

On Windows, check `where uv` if `uv` reports a version error. A Chocolatey
shim can appear before the standalone installer on `PATH`. Use the standalone
installer or upgrade the Chocolatey package from an elevated shell so
`uv --version` reports at least 0.11.23.

## Local setup

Create your local environment file:

```sh
cp .env.example .env
```

Install dependencies:

```sh
uv sync --locked --all-extras --dev
```

Apply database migrations:

```sh
uv run python manage.py migrate
```

Create or update the local development admin account:

```sh
uv run python manage.py ensure_dev_admin
```

Run the Django development server:

```sh
uv run python manage.py runserver
```

The default `.env.example` values target a local PostgreSQL database at
`postgresql://muspy:muspy@localhost:5432/muspy`. Change `.env` for your own
local database credentials.

## Container setup

Validate the Compose file:

```sh
podman compose -f compose.yml config
```

Run Django's system check in containers:

```sh
podman compose -f compose.yml up -d db
podman compose -f compose.yml run --rm web python manage.py check
podman compose -f compose.yml down -v
```

`postgres:18` expects its volume at `/var/lib/postgresql`. Do not move it back
to `/var/lib/postgresql/data`.

## Background workers

This project uses Celery with RabbitMQ for task routing. Redis stores shared
rate-limit state and short locks. PostgreSQL stores durable workflow state.

Run the container stack:

```sh
podman compose -f compose.yml up db broker redis web worker-imports worker-sync worker-notifications worker-maintenance beat
```

Run an imports worker on bare metal:

```sh
uv run celery -A config worker -Q imports --loglevel=info
```

Run a release sync worker on bare metal:

```sh
uv run celery -A config worker -Q sync --loglevel=info
```

Run a notification fanout worker on bare metal:

```sh
uv run celery -A config worker -Q notifications --loglevel=info
```

## Email in development

You do not need a local mail server for development. `.env.example` uses
Django's console email backend:

```sh
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

With that backend, notification email prints to the worker terminal instead of
leaving your machine.

To test SMTP later, set these values in `.env`:

```sh
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-username
EMAIL_HOST_PASSWORD=your-password
EMAIL_USE_TLS=1
DEFAULT_FROM_EMAIL=muspy@example.com
```

Use an app password or provider token when your email provider requires one. Do
not commit SMTP credentials.

## Testing with real data

Use this flow to test MusicBrainz sync, feeds, and notification email with real
release data:

1. Start the local stack:

```sh
podman compose -f compose.yml up db broker redis web worker-sync worker-notifications
```

2. Apply migrations and create the development admin account:

```sh
podman compose -f compose.yml run --rm web python manage.py migrate
podman compose -f compose.yml run --rm web python manage.py ensure_dev_admin
```

3. Open `http://localhost:8000/accounts/login/` and log in with the admin
credentials from `.env`.

4. Use Search Artists to find a real MusicBrainz artist, then follow that
artist. The follow action enqueues release sync.

5. Watch the `worker-sync` logs. When sync finishes, release pages and the
dashboard should show the artist's releases.

6. Open Feed settings, create an RSS or iCal token, copy the URL, and open it in
your browser or feed reader.

7. Set notification cadence to Instant, Daily digest, or Weekly digest. New
synced release events create pending notifications. To force delivery in a local
shell, run:

```sh
podman compose -f compose.yml run --rm web python manage.py shell -c "from releasewatch.tasks import send_pending_notification_emails_task; send_pending_notification_emails_task()"
```

8. With the console email backend, generated email appears in the command output
or notification worker logs.

## Tests and checks

Run a targeted pytest file:

```sh
uv run pytest tests/test_settings_security.py -q
```

Run UI-focused tests:

```sh
uv run pytest tests/test_rate_limits.py tests/test_accessibility_templates.py tests/test_public_release_views.py tests/test_dashboard_follow_views.py tests/test_artist_search_follow_views.py tests/test_import_review_views.py tests/test_notification_settings_view.py -q
```

Run the full test suite with coverage:

```sh
uv run coverage run -m pytest
uv run coverage report
```

Coverage must stay at or above 97%. Treat that number as a ratchet: raise it
when the suite earns it, but do not lower it.

Run linting and security checks:

```sh
uv run ruff check .
uv run bandit -c pyproject.toml -r config releasewatch
uv run python manage.py check
```

## TDD standard

For feature work and bug fixes, write a failing test before changing production
behavior. Keep the test focused on the behavior being added or corrected, then
make the smallest production change that makes the test pass.

## Commit attribution

Use GitHub noreply addresses for commits that should not expose a personal
email address. For this repository, use:

```text
blindndangerous <20344049+blindndangerous@users.noreply.github.com>
```

Commits made with Codex assistance must include both trailers:

```text
Co-authored-by: blindndangerous <20344049+blindndangerous@users.noreply.github.com>
Co-authored-by: Codex <codex@openai.com>
```

Keep trailers in the commit message body, after a blank line. Do not put real
email addresses in commits, examples, or documentation.

## Upstream provider tests

Provider client tests use `httpx.MockTransport`. Do not add live network calls
to the test suite. Configure provider credentials through environment variables:

- `UPSTREAM_HTTP_TIMEOUT_SECONDS`
- `UPSTREAM_CONTACT`
- `UPSTREAM_USER_AGENT`
- `LASTFM_API_KEY`
- `LASTFM_API_SECRET`
