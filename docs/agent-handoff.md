# Agent Handoff

Last updated: 2026-06-21

## Current Phase

Foundation scaffold.

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

## Next Required Step

Continue with Task 8 in docs/superpowers/plans/2026-06-21-muspy-modernization-plan.md.

## Open Questions

None currently blocking. Future implementation may need a specific production host choice.

## Verification Notes

Current checkpoint verification:

- `uv run pytest tests/test_settings_security.py -q`
- `uv run pytest tests/test_project_smoke.py -q`
- `uv run python manage.py check`
- `git status --short --untracked-files=all`
