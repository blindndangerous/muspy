import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

TRUEISH_VALUES = {"1", "true", "yes", "on"}


class Command(BaseCommand):
    help = "Create or update a local development admin account."

    def handle(self, *args, **options):
        if not settings.DEBUG and not _allow_dev_admin_bootstrap():
            raise CommandError("ensure_dev_admin refuses to run without DEBUG or override")

        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "admin")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "admin@example.test")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        if not password:
            raise CommandError("DJANGO_SUPERUSER_PASSWORD is required")

        user_model = get_user_model()
        user, _created = user_model.objects.get_or_create(username=username)
        user.email = email
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()

        self.stdout.write(self.style.SUCCESS(f"Dev admin ready: {username}"))


def _allow_dev_admin_bootstrap() -> bool:
    return os.environ.get("ALLOW_DEV_ADMIN_BOOTSTRAP", "").lower() in TRUEISH_VALUES
