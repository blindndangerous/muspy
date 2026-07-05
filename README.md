# muspy

Muspy is an album release notification service. This repository is a modern
fork of the original project, rebuilt on Django 6.

The legacy Python 2 and Django 1.3 application remains under `legacy/` for
provenance and reference. New work should happen outside `legacy/`.

## Current status

The modern invite-only application is usable for local development and small
trusted deployments. It has accessible server-rendered pages for public
releases, dashboard/follows, artist search and follow, import review,
notification preferences, tokenized RSS/iCal feed URLs, release sync,
notification fanout, and email delivery through Django's email backend.

Accounts are invite-only. An administrator creates an invite code in Django
admin or with the Django shell, then sends the invite URL to the new user. The
user opens `/accounts/signup/<invite-code>/`, creates an account, and is logged
in.

Local development does not require an email server. By default, Django uses the
console email backend and prints generated email to the worker process output.
Production can use any SMTP service by setting Django email environment
variables such as `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`,
`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, and
`DEFAULT_FROM_EMAIL`.

Useful project docs:

- Design spec: `docs/superpowers/specs/2026-06-21-muspy-modernization-design.md`
- Implementation plan: `docs/superpowers/plans/2026-06-21-muspy-modernization-plan.md`
- Agent handoff: `docs/agent-handoff.md`
- Development setup: `docs/development.md`
- Deployment notes: `docs/deployment.md`
- Security notes: `docs/security.md`

## Commit attribution

Use GitHub noreply addresses for commits that should not expose personal email
addresses. Commits made with Codex assistance must include both coauthor
trailers:

```text
Co-authored-by: blindndangerous <20344049+blindndangerous@users.noreply.github.com>
Co-authored-by: Codex <codex@openai.com>
```

## Quick start

Install `uv` 0.11.23 or newer, then install dependencies:

```sh
uv sync --locked --all-extras --dev
```

Run tests:

```sh
uv run pytest
```

For a full local setup, including PostgreSQL, migrations, and the development
admin account, see `docs/development.md`. For testing with live MusicBrainz
data, see `docs/development.md#testing-with-real-data`.
