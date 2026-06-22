import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"


def test_coverage_floor_is_ratcheted_to_current_level():
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert config["tool"]["coverage"]["report"]["fail_under"] == 96


def test_uv_tooling_requires_current_uv_version():
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert config["tool"]["uv"]["required-version"] == ">=0.11.23"


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


def test_task_infrastructure_lockfile_pins_runtime_packages():
    lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    packages = {package["name"]: package["version"] for package in lock["package"]}

    assert packages["celery"] == "5.6.3"
    assert packages["django-celery-beat"] == "2.9.0"
    assert packages["redis"] == "8.0.0"
    assert packages["cryptography"] == "49.0.0"
