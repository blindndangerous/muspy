import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def test_coverage_floor_is_ratcheted_to_current_level():
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert config["tool"]["coverage"]["report"]["fail_under"] == 95


def test_httpx_is_project_dependency():
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    assert "httpx>=0.28,<1.0" in config["project"]["dependencies"]
