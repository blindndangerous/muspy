import os
import sys
from pathlib import Path

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


def _running_tests() -> bool:
    return any("pytest" in Path(arg).name for arg in sys.argv)


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


DEBUG = _env_bool("DEBUG")
SECRET_KEY = _get_secret_key(DEBUG, running_plain_system_check=_running_plain_system_check())

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

DATABASES = {
    "default": dj_database_url.config(
        default="postgresql://muspy:muspy@localhost:5432/muspy",
        conn_max_age=60,
    )
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "muspy@example.test")

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

CELERY_BROKER_URL = os.environ.get(
    "CELERY_BROKER_URL",
    "amqp://guest:guest@localhost:5672//",
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
}
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
PROVIDER_TOKEN_ENCRYPTION_KEY = os.environ.get("PROVIDER_TOKEN_ENCRYPTION_KEY", "")

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_SSL_REDIRECT = _env_bool("SECURE_SSL_REDIRECT")
