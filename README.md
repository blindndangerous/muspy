# muspy

Muspy is an album release notification service. This repository is a modern
fork of the original project, with the new Django implementation in progress.

The legacy Python 2 and Django 1.3 application remains under `legacy/` for
provenance and reference. New work should happen outside `legacy/`.

## Current status

Modernization is in progress. The repository currently contains project
scaffolding, container files, security settings, CI checks, and planning docs.
The user-facing application is still being rebuilt.

Useful project docs:

- Design spec: `docs/superpowers/specs/2026-06-21-muspy-modernization-design.md`
- Implementation plan: `docs/superpowers/plans/2026-06-21-muspy-modernization-plan.md`
- Agent handoff: `docs/agent-handoff.md`
- Development setup: `docs/development.md`
- Deployment notes: `docs/deployment.md`
- Security notes: `docs/security.md`

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
admin account, see `docs/development.md`.
