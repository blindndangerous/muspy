import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def test_coverage_floor_is_ratcheted_to_current_level():
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert config["tool"]["coverage"]["report"]["fail_under"] == 96


def test_httpx_is_project_dependency():
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert "httpx>=0.28,<1.0" in config["project"]["dependencies"]


def test_task_infrastructure_dependencies_are_locked():
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dependencies = config["project"]["dependencies"]

    assert "celery>=5.6,<6.0" in dependencies
    assert "django-celery-beat>=2.9,<3.0" in dependencies
    assert "redis>=8.0,<9.0" in dependencies
    assert "cryptography>=49.0,<50.0" in dependencies
