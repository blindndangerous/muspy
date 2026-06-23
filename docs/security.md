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

Coverage is part of the security baseline. The configured floor is 97%, and it
should only move up.

## Provider tokens

Provider tokens are encrypted before storage. Set
`PROVIDER_TOKEN_ENCRYPTION_KEY` before enabling recurring ListenBrainz imports.
Do not use `SECRET_KEY` as the provider token key.

Celery task arguments must contain database IDs only. Do not pass provider
tokens, API keys, raw payloads, or signed URLs through the broker.

Release sync stores MusicBrainz payloads after normal payload redaction. Keep
sync and notification fanout tasks ID-only: pass artist IDs and release event
IDs, not payloads or user data.

## Rate limits

Rate limits use Django's cache backend. Production deployments must use a shared
Redis cache through `REDIS_URL`; local memory caches are not sufficient across
multiple web workers.

Rate-limit keys must hash user-entered or sensitive values before storage.
