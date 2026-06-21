from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

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

SHA256_HEX_VALIDATOR = RegexValidator(
    regex=r"^[0-9a-fA-F]{64}$",
    message="Enter a valid SHA-256 hex digest.",
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
    token_hash = models.CharField(
        max_length=64,
        unique=True,
        validators=[SHA256_HEX_VALIDATOR],
    )
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


class Invite(models.Model):
    code = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_invites",
    )
    max_uses = models.PositiveIntegerField(default=1)
    uses = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["expires_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_uses__gte=1),
                name="invite_max_uses_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(uses__gte=0),
                name="invite_uses_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(uses__lte=models.F("max_uses")),
                name="invite_uses_lte_max_uses",
            ),
        ]

    def __str__(self) -> str:
        return self.code

    @property
    def can_be_used(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= timezone.now():
            return False
        return self.uses < self.max_uses


class Artist(models.Model):
    mbid = models.UUIDField(unique=True)
    name = models.CharField(max_length=255)
    sort_name = models.CharField(max_length=255, blank=True)
    disambiguation = models.CharField(max_length=255, blank=True)
    artist_type = models.CharField(max_length=64, blank=True)
    country = models.CharField(max_length=2, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    last_refreshed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["sort_name"]),
            models.Index(fields=["last_refreshed_at"]),
        ]
        ordering = ["sort_name", "name"]

    def __str__(self) -> str:
        return self.name


class ArtistAlias(models.Model):
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name="aliases")
    name = models.CharField(max_length=255)
    sort_name = models.CharField(max_length=255, blank=True)
    locale = models.CharField(max_length=16, blank=True)
    alias_type = models.CharField(max_length=64, blank=True)
    primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["locale", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["artist", "name", "locale"],
                name="artist_alias_unique_artist_name_locale",
            )
        ]

    def __str__(self) -> str:
        return self.name


class Follow(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE)
    is_ignored = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "artist"],
                name="follow_unique_user_artist",
            )
        ]
        indexes = [
            models.Index(fields=["user", "is_ignored"]),
            models.Index(fields=["artist"]),
        ]

    def __str__(self) -> str:
        state = "ignored" if self.is_ignored else "following"
        return f"{self.user} {state} {self.artist}"


class ImportRun(models.Model):
    class Source(models.TextChoices):
        LASTFM = "lastfm", "Last.fm"
        LISTENBRAINZ = "listenbrainz", "ListenBrainz"
        PLAIN_TEXT = "plain_text", "Plain text"

    class Status(models.TextChoices):
        STARTED = "started", "Started"
        PENDING_REVIEW = "pending_review", "Pending review"
        APPLIED = "applied", "Applied"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    source = models.CharField(max_length=32, choices=Source)
    status = models.CharField(max_length=32, choices=Status, default=Status.STARTED)
    raw_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "source", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.source} import for {self.user}"


class ImportCandidate(models.Model):
    class ReviewState(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        IGNORED = "ignored", "Ignored"
        REJECTED = "rejected", "Rejected"

    import_run = models.ForeignKey(
        ImportRun,
        on_delete=models.CASCADE,
        related_name="candidates",
    )
    artist = models.ForeignKey(Artist, null=True, blank=True, on_delete=models.SET_NULL)
    source_name = models.CharField(max_length=255)
    source_identifier = models.CharField(max_length=255, blank=True)
    review_state = models.CharField(
        max_length=16,
        choices=ReviewState,
        default=ReviewState.PENDING,
    )
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["import_run", "review_state"]),
            models.Index(fields=["source_identifier"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["import_run", "source_identifier"],
                condition=~models.Q(source_identifier=""),
                name="import_candidate_unique_run_identifier",
            )
        ]

    def __str__(self) -> str:
        return self.source_name
