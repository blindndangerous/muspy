# Agent Handoff

Last updated: 2026-06-21

## Current Phase

Domain models in progress. Account, notification preference, feed token, invite, artist, follow, and import models are complete.

## Repository

- Remote: `blindndangerous/muspy`
- Local path: `C:\Users\blind\gitrepos\muspy`
- Branch: `modernization-design`

## Goal

Create a modern Muspy successor using Django 6, Python 3.14 or 3.13, PostgreSQL 18, `uv`, and Podman/Docker Compose support. Legacy code remains reference only.

## Read First After Context Compact

1. `docs/agent-handoff.md`
2. `docs/superpowers/specs/2026-06-21-muspy-modernization-design.md`
3. `docs/superpowers/plans/2026-06-21-muspy-modernization-plan.md` once it exists
4. `git status`

## Approved Decisions

- Rebuild conceptually; do not patch Python 2/Django 1.3 code.
- Keep fork for provenance.
- Use app package name `releasewatch`.
- Use Django 6.
- Use PostgreSQL 18.
- Use `uv` for dependency and command workflow.
- Support bare metal, Podman Compose, and Docker Compose.
- Use server-rendered accessible HTML, not SPA.
- Use invite-only accounts for MVP.
- Let users choose notification cadence: off, daily, weekly, instant.
- Use MusicBrainz as canonical source, ListenBrainz for imports/fresh-release help, Last.fm for import only.
- Use tokenized RSS/iCal URLs.
- Add dev-only admin bootstrap command during implementation.
- Adopt strict TDD wherever practical.
- Build broad test coverage and security checks from the start.
- Use git commits as checkpoints. Record last known good commit here after each verified phase.

## Checkpoint Policy

- Commit planning docs before implementation starts.
- Commit after each verified phase.
- Keep commits small and revertable.
- Create a named checkpoint branch or tag before risky migrations, broad refactors, or task backend changes.
- Prefer targeted revert or follow-up fix commits over rewriting shared history.
- Update this file with the last known good commit and next action before long pauses.

## Last Known Good Commit

- `326f332` - `docs: add modernization design`
- `ae80057` - `docs: add foundation implementation plan`
- `7447ab9` - `chore: remove legacy move manifest`
- `2a9ba82` - Task 2 checkpoint
- `3b041e8` - Task 2 handoff fix
- `4ec07f7` - `chore: add django foundation`
- `467e93e` - `chore: add container and ci foundation`
- `8591cce` - `ci: load bandit config`
- `2854f1f` - `docs: add foundation setup guidance`
- `14b4bcc` - `docs: add domain model plan`
- `306ee07` - `docs: tighten domain model plan`
- `69937a4` - `docs: fix domain plan verification env`
- `da86c19` - `feat: add account domain models`
- `ead4f8f` - `fix: validate feed token hashes`
- `9bdd01d` - `feat: add artist and import domain models`

## Next Required Step

Continue with Task 5 in docs/superpowers/plans/2026-06-21-domain-models-plan.md.

## Open Questions

None currently blocking. Future implementation may need a specific production host choice.

## Verification Notes

Current checkpoint verification:

- `uv run pytest tests/test_settings_security.py -q`
- `uv run coverage run -m pytest tests/test_settings_security.py -q`
- `uv run coverage run --append -m pytest tests/test_dev_admin_command.py tests/test_project_smoke.py tests/test_container_files.py tests/test_ci_workflow.py -q`
- `uv run coverage report`
- `uv run ruff check .`
- `uv run bandit -c pyproject.toml -r config releasewatch`
- `uv run python manage.py check`
- `uv run ruff check releasewatch tests/test_domain_models.py`
- `DEBUG=1 SECRET_KEY=domain-test-secret DATABASE_URL=sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-domain.sqlite3 uv run pytest tests/test_domain_models.py -q` passed with 15 tests
- `DEBUG=1 SECRET_KEY=domain-test-secret DATABASE_URL=sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-domain.sqlite3 uv run python manage.py makemigrations --check --dry-run`
- `.env` exists locally from `.env.example`
- `podman-compose`, `podman`, and `docker` are not installed on this machine, so Task 10 container runtime verification could not run locally
- `git status --short --untracked-files=all`
