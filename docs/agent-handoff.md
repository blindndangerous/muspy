# Agent Handoff

Last updated: 2026-06-22

## Current Phase

Task infrastructure and import workflow plan in progress. Sync/import workflow design complete. Upstream clients complete. Domain models complete.

## Repository

- Remote: `blindndangerous/muspy`
- Local path: `C:\Users\blind\gitrepos\muspy`
- Branch: `modernization-design`

## Goal

Create a modern Muspy successor using Django 6, Python 3.14, PostgreSQL 18, `uv`, and Podman/Docker Compose support. Legacy code remains reference only.

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
- Build broad test coverage and security checks from the start. Coverage floor is 96% and ratchets up only.
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
- `1b42d5f` - `feat: add release and notification domain models`
- `8c60f14` - `feat: register domain models in admin`
- `e1f07d4` - `test: ratchet coverage floor to 95`
- `a827db2` - `docs: add upstream client plan`
- `c65d22b` - `docs: record upstream plan checkpoint`
- `3da5e20` - `chore: add upstream client settings`
- `5e9c6f9` - `fix: harden upstream setting defaults`
- `05af046` - `feat: add upstream client base`
- `f626335` - `test: cover upstream base edge cases`
- `432ff53` - `fix: harden upstream base client`
- `3b2cc47` - `fix: enforce upstream request origin`
- `c1cb923` - `feat: add musicbrainz client`
- `a9012e4` - `fix: harden musicbrainz client`
- `5aaa7a5` - `fix: isolate musicbrainz payloads`
- `43ccc47` - `feat: add listenbrainz client`
- `18ebf91` - `fix: harden listenbrainz client`
- `44a11c8` - `fix: isolate listenbrainz auth redaction`
- `4d4ee40` - `fix: isolate listenbrainz rate metadata`
- `3385b49` - `feat: add lastfm client`
- `ac86608` - `fix: redact lastfm http error payloads`
- `c416a27` - `fix: harden lastfm payload handling`
- `cae176c` - `fix: clean smoke warnings and podman db mount`
- `f5327ab` - `test: ratchet coverage floor to 96`
- `dcc7141` - `docs: add sync import workflow design`

## Next Required Step

Review `docs/superpowers/plans/2026-06-22-task-import-workflows-plan.md`, then execute with subagent-driven development.

## Open Questions

None currently blocking. Future implementation may need a specific production host choice.

## Verification Notes

Latest full verification:

- `uv run coverage run -m pytest tests/test_settings_security.py tests/test_quality_config.py tests/test_upstream_base.py tests/test_musicbrainz_client.py tests/test_listenbrainz_client.py tests/test_lastfm_client.py -q`
- `DEBUG=1 DATABASE_URL=sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-domain.sqlite3 uv run coverage run --append -m pytest tests/test_domain_models.py tests/test_dev_admin_command.py tests/test_project_smoke.py tests/test_container_files.py tests/test_ci_workflow.py -q`
- `uv run coverage report`
- `uv run ruff check .`
- `uv run bandit -c pyproject.toml -r config releasewatch`
- `uv run python manage.py check`
- `podman build -f Containerfile -t muspy:dev .`
- `podman compose -f compose.yml config`
- `podman compose -f compose.yml up -d db; podman compose -f compose.yml run --rm web python manage.py check; podman compose -f compose.yml down -v`
- Latest full run passed:
  - upstream/settings pytest group: 123 passed.
  - domain/dev/smoke/container/CI pytest group: 46 passed.
  - coverage: 96%, floor 96%.
  - Ruff: passed.
  - Bandit: no issues.
  - Django check: no issues.
  - Podman build: passed.
  - Podman Compose config: passed.
  - Podman Compose `web python manage.py check` with healthy Postgres 18: passed.
- Focused checks before docs update:
  - Last.fm re-review approved `c416a27`.
  - `uv run pytest tests/test_lastfm_client.py -q`: 38 passed.
  - `uv run ruff check releasewatch/upstreams/lastfm.py tests/test_lastfm_client.py`: passed.
  - `uv run pytest tests/test_project_smoke.py -q -W always`: 3 passed, no warnings.
  - `uv run pytest tests/test_container_files.py::test_compose_wires_database_health_env_and_web_port -q`: passed.
  - `podman build -f Containerfile -t muspy:dev .`: passed.
  - `podman compose -f compose.yml config`: passed.
  - `podman compose -f compose.yml run --rm web python manage.py check`: passed after db was healthy.
- `.env` exists locally from `.env.example`
- Podman CLI 5.8.1 installed with Chocolatey.
- Podman machine `podman-machine-default` exists and was started.
- Docker Compose v5.1.4 installed with Winget as Podman Compose provider. Current shell may need this path prepended until restarted: `C:\Users\blind\AppData\Local\Microsoft\WinGet\Packages\Docker.DockerCompose_Microsoft.Winget.Source_8wekyb3d8bbwe`.
- Project now requires `uv>=0.11.23` through `[tool.uv].required-version`.
- CI pins `astral-sh/setup-uv@v8.2.0` with `version: "0.11.23"`.
- Containerfile pins `ghcr.io/astral-sh/uv:0.11.23-python3.14-trixie-slim`.
- `uv` on PATH resolves to Chocolatey `0.11.18`; Chocolatey reports `0.11.23` available but non-admin upgrade fails on `C:\ProgramData\chocolatey`.
- `uv self update` on the Chocolatey binary fails because self-update only works for standalone installer binaries.
- Latest local uv is `C:\Users\blind\.local\bin\uv.exe` at `0.11.23`; use that explicit path until Chocolatey uv is upgraded from an elevated shell or PATH precedence changes.
- Latest lock refresh command run with local uv `0.11.23`: `C:\Users\blind\.local\bin\uv.exe lock --upgrade`. It resolved successfully and produced no `uv.lock` diff.
- `C:\Users\blind\.local\bin\uv.exe lock --check`: passed.
- `uv lock --check` with PATH Chocolatey `0.11.18`: fails fast with required-version error.
- `C:\Users\blind\.local\bin\uv.exe run pytest tests/test_quality_config.py tests/test_ci_workflow.py tests/test_container_files.py -q`: 19 passed.
- `C:\Users\blind\.local\bin\uv.exe run ruff check tests/test_quality_config.py tests/test_ci_workflow.py tests/test_container_files.py`: passed.
- `git status --short --untracked-files=all`
