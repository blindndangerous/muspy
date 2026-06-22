import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from config import settings as app_settings


def test_get_secret_key_requires_env_outside_debug_or_tests(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(ImproperlyConfigured):
        app_settings._get_secret_key(debug=False, running_tests=False)


def test_get_secret_key_allows_dev_fallback_when_debug(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)

    assert app_settings._get_secret_key(debug=True, running_tests=False) == "dev-only-change-me"


def test_get_secret_key_allows_dev_fallback_when_running_tests(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)

    assert app_settings._get_secret_key(debug=False, running_tests=True) == "dev-only-change-me"


def test_get_secret_key_allows_dev_fallback_for_plain_system_check(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)

    assert (
        app_settings._get_secret_key(
            debug=False,
            running_tests=False,
            running_plain_system_check=True,
        )
        == "dev-only-change-me"
    )


def test_get_secret_key_prefers_env_secret(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "real-secret")

    assert app_settings._get_secret_key(debug=False, running_tests=False) == "real-secret"


def test_running_tests_detects_coverage_running_pytest(monkeypatch):
    monkeypatch.setattr(app_settings.sys, "argv", ["coverage", "run", "-m", "pytest"])

    assert app_settings._running_tests() is True


def test_running_tests_ignores_imported_pytest_module(monkeypatch):
    monkeypatch.setattr(app_settings.sys, "argv", ["manage.py", "check", "--deploy"])

    assert app_settings._running_tests() is False


def test_upstream_timeout_rejects_invalid_value(monkeypatch):
    monkeypatch.setenv("UPSTREAM_HTTP_TIMEOUT_SECONDS", "not-an-int")

    with pytest.raises(ImproperlyConfigured, match="UPSTREAM_HTTP_TIMEOUT_SECONDS"):
        app_settings._env_int("UPSTREAM_HTTP_TIMEOUT_SECONDS", default=10, minimum=1, maximum=60)


def test_upstream_timeout_rejects_out_of_range_value(monkeypatch):
    monkeypatch.setenv("UPSTREAM_HTTP_TIMEOUT_SECONDS", "0")

    with pytest.raises(ImproperlyConfigured, match="between 1 and 60"):
        app_settings._env_int("UPSTREAM_HTTP_TIMEOUT_SECONDS", default=10, minimum=1, maximum=60)


def test_running_tests_detects_pytest_script(monkeypatch):
    monkeypatch.setattr(app_settings.sys, "argv", ["pytest", "tests/test_settings_security.py"])

    assert app_settings._running_tests() is True


def test_database_uses_postgresql_by_default():
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"


def test_secure_cookie_settings_follow_debug_mode():
    assert settings.SESSION_COOKIE_SECURE is (not settings.DEBUG)
    assert settings.CSRF_COOKIE_SECURE is (not settings.DEBUG)


def test_upstream_client_settings_have_safe_defaults():
    assert settings.UPSTREAM_HTTP_TIMEOUT_SECONDS == 10
    assert settings.UPSTREAM_USER_AGENT.startswith("muspy/")
    assert "example.invalid" in settings.UPSTREAM_CONTACT
    assert settings.LASTFM_API_KEY == ""
    assert settings.LASTFM_API_SECRET == ""
