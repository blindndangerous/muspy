# Deployment

Review `docs/security.md` before exposing an instance to real users.

The Compose file in this repository is for local development and smoke testing.
It uses `DEBUG=1`, the example secret key, and Django's development server. Do
not put that Compose stack on the public internet.

## Local Podman Compose

Build and start the local app stack with Podman Compose:

```sh
podman compose up --build
```

Run migrations in the web container:

```sh
podman compose run --rm web python manage.py migrate
```

Run Django's deployment check from inside the local web container:

```sh
podman compose run --rm web python manage.py check --deploy
```

## Local Docker Compose

Build and start the local app stack with Docker Compose:

```sh
docker compose up --build
```

Run migrations in the web container:

```sh
docker compose run --rm web python manage.py migrate
```

Run Django's deployment check from inside the local web container:

```sh
docker compose run --rm web python manage.py check --deploy
```

## Bare metal

For a bare metal deployment, install `uv`, provide PostgreSQL 18, and configure
the app through environment variables.

Required production environment values include:

- `DEBUG=0`
- `SECRET_KEY` set to a strong private value
- `DATABASE_URL` pointing at the production PostgreSQL database
- `ALLOWED_HOSTS` set to the deployed hostnames
- Email settings for outbound notifications when notifications are enabled:
  `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`,
  `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, and `DEFAULT_FROM_EMAIL`

Install locked dependencies:

```sh
uv sync --locked --all-extras --no-dev
```

Apply migrations:

```sh
uv run --no-dev python manage.py migrate
```

Run Django deployment checks:

```sh
uv run --no-dev python manage.py check --deploy
```

Use your normal process manager or platform service definition to run the WSGI
or ASGI entry point. Do not run Django's development server for production
traffic.

Run Celery workers for imports, sync, notifications, and maintenance. The
notification worker sends pending email through Django's configured email
backend.

## Admin bootstrap

`ensure_dev_admin` is for local and development bootstrap. It refuses to run
when `DEBUG=0` unless `ALLOW_DEV_ADMIN_BOOTSTRAP=1` is set.

Only use that production override for a controlled one-time bootstrap. Do not
use a shared password, a committed password, or the example password from
`.env.example`.
