# Security

Security baseline for the modern Muspy fork.

## Baseline

- Keep secrets in environment variables. Do not commit real `SECRET_KEY`,
  database passwords, email credentials, API keys, or admin passwords.
- Run production with `DEBUG=0`.
- Keep CSRF protection on for mutating forms and requests.
- Future RSS and iCal feed URLs that expose private user data should use
  tokenized, revocable URLs.
- Enforce owner checks before reading or changing user-owned artists,
  subscriptions, feeds, notification settings, or account data.
- Verify email addresses before sending release notifications.
- Support account deletion with deletion or anonymization of user-owned data
  where required.

## Security checks

Run these before merging security-sensitive changes:

```sh
uv run ruff check .
uv run bandit -c pyproject.toml -r config releasewatch
uv run python manage.py check --deploy
uv run coverage run -m pytest
uv run coverage report
```

Coverage is part of the security baseline. The configured floor is 96%, and it
should only move up.
