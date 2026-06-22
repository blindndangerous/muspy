import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_project_file(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_compose_defines_database_and_django_services():
    compose = read_project_file("compose.yml")

    assert "postgres:18" in compose
    assert "x-podman" in compose
    for service in (
        "web",
        "worker-imports",
        "worker-sync",
        "worker-notifications",
        "worker-maintenance",
        "beat",
    ):
        assert f"  {service}:" in compose
        assert "build:" in compose
        assert "context: ." in compose
        assert "dockerfile: Containerfile" in compose


def test_compose_defines_rabbitmq_redis_dedicated_workers_and_beat():
    compose = read_project_file("compose.yml")

    for service in (
        "broker",
        "redis",
        "worker-imports",
        "worker-sync",
        "worker-notifications",
        "worker-maintenance",
        "beat",
    ):
        assert f"  {service}:" in compose

    assert "rabbitmq:4-management" in compose
    assert "redis:8" in compose
    assert "CELERY_BROKER_URL=amqp://muspy:muspy@broker:5672//" in compose
    assert "REDIS_URL=redis://redis:6379/0" in compose
    assert "celery" in compose
    assert "-Q" in compose
    assert "imports" in compose
    assert "sync" in compose
    assert "notifications" in compose
    assert "maintenance" in compose


def test_compose_wires_database_health_env_and_web_port():
    compose = read_project_file("compose.yml")

    assert "POSTGRES_DB: muspy" in compose
    assert "POSTGRES_USER: muspy" in compose
    assert "POSTGRES_PASSWORD: muspy" in compose
    assert "pg_isready" in compose
    assert "muspy-postgres-data:" in compose
    assert "/var/lib/postgresql/data" not in compose
    assert "/var/lib/postgresql" in compose
    assert "DATABASE_URL=postgresql://muspy:muspy@db:5432/muspy" in compose
    assert "condition: service_healthy" in compose
    assert '"8000:8000"' in compose
    assert "0.0.0.0:8000" in compose


def test_containerfile_uses_locked_uv_workflow():
    containerfile = read_project_file("Containerfile")

    assert "uv sync --locked" in containerfile
    assert "uv.lock" in containerfile
    assert "pyproject.toml" in containerfile
    assert "EXPOSE 8000" in containerfile
    assert "0.0.0.0:8000" in containerfile


def test_containerfile_prevents_runtime_uv_sync_and_dev_dependencies():
    containerfile = read_project_file("Containerfile")

    assert "UV_NO_DEV=1" in containerfile
    assert "UV_NO_SYNC=1" in containerfile
    cmd_line = next(
        line for line in containerfile.splitlines() if line.startswith("CMD ")
    )
    assert '"uv"' not in cmd_line
    assert '"run"' not in cmd_line
    assert '"python"' in cmd_line
    assert '"manage.py"' in cmd_line


def test_compose_runtime_commands_do_not_use_uv_run():
    compose = read_project_file("compose.yml")

    for service in (
        "web",
        "worker-imports",
        "worker-sync",
        "worker-notifications",
        "worker-maintenance",
        "beat",
    ):
        match = re.search(
            rf"^  {service}:\n(?P<block>(?:    .*\n?)+)",
            compose,
            re.MULTILINE,
        )
        assert match is not None
        service_block = match.group("block")
        command_line = next(
            line for line in service_block.splitlines() if "command:" in line
        )
        assert '"uv"' not in command_line
        assert '"run"' not in command_line

    assert '"python", "manage.py"' in compose
    assert '"celery", "-A", "config", "worker"' in compose
    assert '"celery", "-A", "config", "beat"' in compose


def test_containerignore_excludes_local_and_legacy_artifacts():
    ignore = read_project_file(".containerignore")

    for pattern in (
        ".git",
        ".gitignore",
        ".env",
        ".env.*",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".coverage",
        "htmlcov",
        "legacy/*.sqlite3",
        "legacy/*.db",
    ):
        assert pattern in ignore


def test_dockerignore_matches_containerignore_critical_patterns():
    containerignore = read_project_file(".containerignore")
    dockerignore = read_project_file(".dockerignore")

    for pattern in (
        ".git",
        ".gitignore",
        ".env",
        ".env.*",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".coverage",
        "coverage.xml",
        "htmlcov",
        "staticfiles",
        "legacy/*.sqlite3",
        "legacy/*.sqlite",
        "legacy/*.db",
    ):
        assert pattern in containerignore
        assert pattern in dockerignore
