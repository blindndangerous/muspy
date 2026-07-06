import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default

    return value.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError as error:
        raise ImproperlyConfigured(f"{name} must be an integer.") from error

    if not minimum <= value <= maximum:
        raise ImproperlyConfigured(f"{name} must be between {minimum} and {maximum}.")

    return value


def _env_required(
    name: str,
    *,
    default: str,
    debug: bool,
    running_tests: bool | None = None,
    running_plain_system_check: bool = False,
) -> str:
    value = os.environ.get(name)
    if value:
        return value

    if running_tests is None:
        running_tests = _running_tests()

    if debug or running_tests or running_plain_system_check:
        return default

    raise ImproperlyConfigured(f"{name} environment variable must be set when DEBUG is false.")


def _public_base_url(
    debug: bool,
    running_tests: bool | None = None,
    running_plain_system_check: bool = False,
) -> str:
    if running_tests is None:
        running_tests = _running_tests()

    value = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not value:
        if debug or running_tests or running_plain_system_check:
            return "http://localhost:8000"
        raise ImproperlyConfigured(
            "PUBLIC_BASE_URL environment variable must be set when DEBUG is false."
        )

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ImproperlyConfigured("PUBLIC_BASE_URL must be an absolute HTTP or HTTPS URL.")

    host = parsed.hostname or ""
    if (
        not debug
        and not running_tests
        and not running_plain_system_check
        and (
            host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}  # noqa: S104  # nosec B104
            or host.endswith(".localhost")
        )
    ):
        raise ImproperlyConfigured("PUBLIC_BASE_URL must not use a localhost host in production.")

    return value


def _running_tests() -> bool:
    for arg in sys.argv:
        normalized = arg.replace("\\", "/")
        name = normalized.rsplit("/", 1)[-1]
        if name in {"pytest", "pytest.exe"}:
            return True
        if name == "__main__.py" and any(
            part.lower() == "pytest" for part in normalized.split("/")
        ):
            return True
    return False


def _running_plain_system_check() -> bool:
    return len(sys.argv) > 1 and sys.argv[1] == "check" and "--deploy" not in sys.argv[2:]


def _get_secret_key(
    debug: bool,
    running_tests: bool | None = None,
    running_plain_system_check: bool = False,
) -> str:
    secret_key = os.environ.get("SECRET_KEY")
    if secret_key:
        return secret_key

    if running_tests is None:
        running_tests = _running_tests()

    if debug or running_tests or running_plain_system_check:
        return "dev-only-change-me"

    raise ImproperlyConfigured("SECRET_KEY environment variable must be set when DEBUG is false.")


def _staticfiles_storage_backend(debug: bool, running_tests: bool | None = None) -> str:
    if running_tests is None:
        running_tests = _running_tests()

    if debug or running_tests:
        return "django.contrib.staticfiles.storage.StaticFilesStorage"

    return "whitenoise.storage.CompressedManifestStaticFilesStorage"


def _database_config() -> dict:
    return dj_database_url.config(
        default="postgresql://muspy:muspy@localhost:5432/muspy",
        conn_max_age=60,
    )


DEBUG = _env_bool("DEBUG")
SECRET_KEY = _get_secret_key(DEBUG, running_plain_system_check=_running_plain_system_check())
PUBLIC_BASE_URL = _public_base_url(DEBUG, running_plain_system_check=_running_plain_system_check())

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_celery_beat",
    "releasewatch",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {"default": _database_config()}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
_STATICFILES_STORAGE_BACKEND = _staticfiles_storage_backend(DEBUG)
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": _STATICFILES_STORAGE_BACKEND,
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_REDIRECT_URL = "releasewatch:dashboard"

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "muspy@example.test")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = _env_int("EMAIL_PORT", default=25, minimum=1, maximum=65535)
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS")
EMAIL_USE_SSL = _env_bool("EMAIL_USE_SSL")
EMAIL_TIMEOUT = _env_int("EMAIL_TIMEOUT", default=10, minimum=1, maximum=120)

UPSTREAM_HTTP_TIMEOUT_SECONDS = _env_int(
    "UPSTREAM_HTTP_TIMEOUT_SECONDS",
    default=10,
    minimum=1,
    maximum=60,
)
UPSTREAM_CONTACT = os.environ.get("UPSTREAM_CONTACT", "https://example.invalid/contact")
UPSTREAM_USER_AGENT = os.environ.get(
    "UPSTREAM_USER_AGENT",
    f"muspy/{os.environ.get('MUSPY_VERSION', '0.1.0')} ({UPSTREAM_CONTACT})",
)
LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY", "")
LASTFM_API_SECRET = os.environ.get("LASTFM_API_SECRET", "")

CELERY_BROKER_URL = _env_required(
    "CELERY_BROKER_URL",
    default="amqp://guest:guest@localhost:5672//",
    debug=DEBUG,
    running_plain_system_check=_running_plain_system_check(),
)
CELERY_TASK_DEFAULT_QUEUE = "maintenance"
CELERY_TASK_IGNORE_RESULT = True
CELERY_RESULT_BACKEND = None
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "UTC"
CELERY_TASK_ROUTES = {
    "releasewatch.tasks.run_import": {"queue": "imports"},
    "releasewatch.tasks.import_provider_account": {"queue": "imports"},
    "releasewatch.tasks.enqueue_due_provider_imports": {"queue": "maintenance"},
    "releasewatch.tasks.sync_artist_releases_task": {"queue": "sync"},
    "releasewatch.tasks.fanout_release_notifications": {"queue": "notifications"},
    "releasewatch.tasks.send_pending_notification_emails_task": {"queue": "notifications"},
    "releasewatch.tasks.enqueue_due_artist_syncs": {"queue": "maintenance"},
}
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

RELEASE_SYNC_FRESHNESS_HOURS = _env_int(
    "RELEASE_SYNC_FRESHNESS_HOURS",
    default=24,
    minimum=1,
    maximum=720,
)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

RATE_LIMIT_ARTIST_SEARCH_AUTHENTICATED = (
    _env_int("RATE_LIMIT_ARTIST_SEARCH_AUTHENTICATED_COUNT", default=60, minimum=1, maximum=600),
    _env_int("RATE_LIMIT_ARTIST_SEARCH_AUTHENTICATED_WINDOW", default=60, minimum=1, maximum=3600),
)
RATE_LIMIT_FOLLOW_MUTATION = (
    _env_int("RATE_LIMIT_FOLLOW_MUTATION_COUNT", default=60, minimum=1, maximum=600),
    _env_int("RATE_LIMIT_FOLLOW_MUTATION_WINDOW", default=60, minimum=1, maximum=3600),
)
RATE_LIMIT_IMPORT_CREATE = (
    _env_int("RATE_LIMIT_IMPORT_CREATE_COUNT", default=10, minimum=1, maximum=200),
    _env_int("RATE_LIMIT_IMPORT_CREATE_WINDOW", default=3600, minimum=60, maximum=86400),
)
RATE_LIMIT_IMPORT_REVIEW = (
    _env_int("RATE_LIMIT_IMPORT_REVIEW_COUNT", default=120, minimum=1, maximum=1000),
    _env_int("RATE_LIMIT_IMPORT_REVIEW_WINDOW", default=60, minimum=1, maximum=3600),
)
RATE_LIMIT_NOTIFICATION_SETTINGS = (
    _env_int("RATE_LIMIT_NOTIFICATION_SETTINGS_COUNT", default=30, minimum=1, maximum=300),
    _env_int("RATE_LIMIT_NOTIFICATION_SETTINGS_WINDOW", default=60, minimum=1, maximum=3600),
)
RATE_LIMIT_ACCOUNT_PASSWORD = (
    _env_int("RATE_LIMIT_ACCOUNT_PASSWORD_COUNT", default=10, minimum=1, maximum=100),
    _env_int("RATE_LIMIT_ACCOUNT_PASSWORD_WINDOW", default=3600, minimum=60, maximum=86400),
)
PROVIDER_TOKEN_ENCRYPTION_KEY = os.environ.get("PROVIDER_TOKEN_ENCRYPTION_KEY", "")

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_SSL_REDIRECT = _env_bool("SECURE_SSL_REDIRECT")
