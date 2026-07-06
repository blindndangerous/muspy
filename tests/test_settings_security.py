import os

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


def test_running_tests_detects_python_m_pytest(monkeypatch):
    monkeypatch.setattr(app_settings.sys, "argv", ["python", "-m", "pytest"])

    assert app_settings._running_tests() is True


def test_running_tests_detects_pytest_module_entrypoint(monkeypatch):
    monkeypatch.setattr(
        app_settings.sys,
        "argv",
        [r"C:\repo\.venv\Lib\site-packages\pytest\__main__.py", "-k", "settings"],
    )

    assert app_settings._running_tests() is True


def test_running_tests_detects_pytest_executable_path(monkeypatch):
    monkeypatch.setattr(app_settings.sys, "argv", [r"C:\tools\pytest.exe"])

    assert app_settings._running_tests() is True


def test_running_tests_ignores_non_pytest_tokens_containing_pytest(monkeypatch):
    monkeypatch.setattr(app_settings.sys, "argv", ["manage.py", "collectstatic", "--pytest-output"])

    assert app_settings._running_tests() is False


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


def test_staticfiles_storage_uses_plain_storage_in_debug():
    assert (
        app_settings._staticfiles_storage_backend(debug=True, running_tests=False)
        == "django.contrib.staticfiles.storage.StaticFilesStorage"
    )


def test_staticfiles_storage_uses_plain_storage_when_running_tests():
    assert (
        app_settings._staticfiles_storage_backend(debug=False, running_tests=True)
        == "django.contrib.staticfiles.storage.StaticFilesStorage"
    )


def test_staticfiles_storage_uses_manifest_storage_in_production():
    assert (
        app_settings._staticfiles_storage_backend(debug=False, running_tests=False)
        == "whitenoise.storage.CompressedManifestStaticFilesStorage"
    )


def test_database_uses_postgresql_by_default(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert app_settings._database_config()["ENGINE"] == "django.db.backends.postgresql"


def test_secure_cookie_settings_follow_debug_mode():
    assert app_settings.SESSION_COOKIE_SECURE is (not app_settings.DEBUG)
    assert app_settings.CSRF_COOKIE_SECURE is (not app_settings.DEBUG)


def test_upstream_client_settings_have_safe_defaults():
    assert settings.UPSTREAM_HTTP_TIMEOUT_SECONDS == 10
    assert settings.UPSTREAM_USER_AGENT.startswith("muspy/")
    assert "example.invalid" in settings.UPSTREAM_CONTACT
    assert settings.LASTFM_API_KEY == ""
    assert settings.LASTFM_API_SECRET == ""


def test_email_settings_have_local_defaults_and_env_override():
    expected_backend = os.environ.get(
        "EMAIL_BACKEND",
        "django.core.mail.backends.console.EmailBackend",
    )

    assert app_settings.EMAIL_BACKEND == expected_backend
    assert app_settings.DEFAULT_FROM_EMAIL == "muspy@example.test"
    assert app_settings.EMAIL_HOST == "localhost"
    assert app_settings.EMAIL_PORT == 25
    assert app_settings.EMAIL_USE_TLS is False
    assert app_settings.EMAIL_USE_SSL is False


def test_task_infrastructure_settings_have_production_defaults(settings):
    assert settings.CELERY_BROKER_URL.startswith("amqp://")
    assert settings.CELERY_TASK_IGNORE_RESULT is True
    assert settings.CELERY_TASK_DEFAULT_QUEUE == "maintenance"
    assert settings.CELERY_TASK_SERIALIZER == "json"
    assert settings.CELERY_ACCEPT_CONTENT == ["json"]
    assert settings.REDIS_URL.startswith("redis://")
    assert settings.PROVIDER_TOKEN_ENCRYPTION_KEY == ""


def test_celery_broker_url_requires_env_outside_debug_or_tests(monkeypatch):
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)

    with pytest.raises(ImproperlyConfigured, match="CELERY_BROKER_URL"):
        app_settings._env_required(
            "CELERY_BROKER_URL",
            default="amqp://guest:guest@localhost:5672//",
            debug=False,
            running_tests=False,
        )


def test_redis_cache_is_configured_from_redis_url(settings):
    assert settings.CACHES["default"]["BACKEND"] == "django.core.cache.backends.redis.RedisCache"
    assert settings.CACHES["default"]["LOCATION"] == settings.REDIS_URL


def test_rate_limit_settings_are_bounded(settings):
    assert settings.RATE_LIMIT_ARTIST_SEARCH_AUTHENTICATED == (60, 60)
    assert settings.RATE_LIMIT_FOLLOW_MUTATION == (60, 60)
    assert settings.RATE_LIMIT_IMPORT_CREATE == (10, 3600)
    assert settings.RATE_LIMIT_IMPORT_REVIEW == (120, 60)
    assert settings.RATE_LIMIT_NOTIFICATION_SETTINGS == (30, 60)
    assert settings.RATE_LIMIT_ACCOUNT_PASSWORD == (10, 3600)
