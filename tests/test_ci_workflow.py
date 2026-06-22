from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def read_workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_ci_workflow_runs_on_expected_events_and_branches():
    workflow = read_workflow()

    assert "pull_request:" in workflow
    assert "push:" in workflow
    for branch in ("main", "master", "modernization-design"):
        assert f"- {branch}" in workflow


def test_ci_workflow_uses_postgresql_18_dev_service():
    workflow = read_workflow()

    assert "postgres:18" in workflow
    assert "POSTGRES_DB: muspy" in workflow
    assert "POSTGRES_USER: muspy" in workflow
    assert "POSTGRES_PASSWORD: muspy" in workflow
    assert "pg_isready -U muspy -d muspy" in workflow


def test_ci_workflow_pins_actions_and_sets_env():
    workflow = read_workflow()

    assert "actions/checkout@v6" in workflow
    assert "astral-sh/setup-uv@v8.2.0" in workflow
    assert "astral-sh/setup-uv@v8\n" not in workflow
    assert 'version: "0.11.23"' in workflow
    assert "DEBUG: \"1\"" in workflow
    assert "SECRET_KEY: ci-secret" in workflow
    assert "ALLOWED_HOSTS: localhost,127.0.0.1" in workflow
    assert "DATABASE_URL: postgresql://muspy:muspy@localhost:5432/muspy" in workflow
    assert (
        "EMAIL_BACKEND: django.core.mail.backends.locmem.EmailBackend"
        in workflow
    )


def test_ci_workflow_runs_required_quality_commands():
    workflow = read_workflow()

    for command in (
        "uv sync --locked --all-extras --dev",
        "uv run ruff check .",
        "uv run python manage.py check",
        "uv run coverage run -m pytest",
        "uv run coverage report",
        "uv run bandit -c pyproject.toml -r config releasewatch",
    ):
        assert command in workflow
