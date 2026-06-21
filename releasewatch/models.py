from django.conf import settings
from django.db import models

SENSITIVE_PAYLOAD_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "email",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)


def redact_payload(value):
    if isinstance(value, dict):
        redacted = {}
        for key, child in value.items():
            normalized_key = str(key).lower()
            if any(sensitive_key in normalized_key for sensitive_key in SENSITIVE_PAYLOAD_KEYS):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = redact_payload(child)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    return value


class NotificationCadence(models.TextChoices):
    OFF = "off", "Off"
    DAILY = "daily", "Daily digest"
    WEEKLY = "weekly", "Weekly digest"
    INSTANT = "instant", "Instant"


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    timezone = models.CharField(max_length=64, default="UTC")
    country = models.CharField(max_length=2, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Profile for {self.user}"

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None


class NotificationPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    cadence = models.CharField(
        max_length=16,
        choices=NotificationCadence,
        default=NotificationCadence.DAILY,
    )
    email_enabled = models.BooleanField(default=True)
    include_future_releases = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Notification preferences for {self.user}"


class FeedToken(models.Model):
    class FeedType(models.TextChoices):
        RSS = "rss", "RSS"
        ICAL = "ical", "iCal"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    feed_type = models.CharField(max_length=8, choices=FeedType)
    token_hash = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=100, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "feed_type"]),
            models.Index(fields=["revoked_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.feed_type} token for {self.user}"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None
