# Development

Use this setup for the modern Muspy fork. The legacy application under
`legacy/` is kept for provenance and reference only.

## Requirements

- `uv`
- Python 3.14, managed by `uv`
- PostgreSQL 18, or Podman Compose or Docker Compose for a containerized
  PostgreSQL 18 database

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

## Tests and checks

Run a targeted pytest file:

```sh
uv run pytest tests/test_settings_security.py -q
```

Run the full test suite with coverage:

```sh
uv run coverage run -m pytest
uv run coverage report
```

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
