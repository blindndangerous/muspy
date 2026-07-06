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
    include_albums = models.BooleanField("Albums", default=True)
    include_singles = models.BooleanField("Singles", default=True)
    include_eps = models.BooleanField("EPs", default=True)
    include_live = models.BooleanField("Live releases", default=True)
    include_compilations = models.BooleanField("Compilations", default=True)
    include_remixes = models.BooleanField("Remixes", default=True)
    include_other_release_types = models.BooleanField("Other release types", default=True)
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


class ProviderAccount(models.Model):
    class Provider(models.TextChoices):
        LASTFM = "lastfm", "Last.fm"
        LISTENBRAINZ = "listenbrainz", "ListenBrainz"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    provider = models.CharField(max_length=32, choices=Provider)
    external_username = models.CharField(max_length=255)
    token_encrypted = models.TextField(blank=True)
    scopes = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.ACTIVE)
    last_imported_at = models.DateTimeField(null=True, blank=True)
    last_error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "provider"]),
            models.Index(fields=["provider", "status"]),
            models.Index(fields=["last_imported_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "provider", "external_username"],
                condition=models.Q(status="active"),
                name="provider_account_unique_user_provider_username",
            )
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.external_username}"


class DatePrecision(models.TextChoices):
    YEAR = "year", "Year"
    MONTH = "month", "Month"
    DAY = "day", "Day"


class ReleaseGroup(models.Model):
    mbid = models.UUIDField(unique=True)
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name="release_groups")
    title = models.CharField(max_length=255)
    primary_type = models.CharField(max_length=64, blank=True)
    secondary_types = models.JSONField(default=list, blank=True)
    first_release_date = models.DateField(null=True, blank=True)
    first_release_precision = models.CharField(
        max_length=8,
        choices=DatePrecision,
        blank=True,
    )
    raw_payload = models.JSONField(default=dict, blank=True)
    last_refreshed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["artist", "title"]),
            models.Index(fields=["first_release_date"]),
            models.Index(fields=["last_refreshed_at"]),
        ]
        ordering = ["artist__sort_name", "first_release_date", "title"]

    def __str__(self) -> str:
        return f"{self.artist} - {self.title}"


class Release(models.Model):
    mbid = models.UUIDField(unique=True)
    release_group = models.ForeignKey(
        ReleaseGroup,
        on_delete=models.CASCADE,
        related_name="releases",
    )
    country = models.CharField(max_length=2, blank=True)
    release_date = models.DateField(null=True, blank=True)
    release_date_precision = models.CharField(
        max_length=8,
        choices=DatePrecision,
        blank=True,
    )
    status = models.CharField(max_length=64, blank=True)
    media_format = models.CharField(max_length=64, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["release_group", "country"]),
            models.Index(fields=["release_date"]),
        ]

    def __str__(self) -> str:
        country = f" ({self.country})" if self.country else ""
        return f"{self.release_group}{country}"


class ReleaseEvent(models.Model):
    release_group = models.ForeignKey(
        ReleaseGroup,
        on_delete=models.CASCADE,
        related_name="events",
    )
    release = models.ForeignKey(
        Release,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="events",
    )
    country = models.CharField(max_length=2, blank=True)
    event_date = models.DateField(null=True, blank=True)
    date_precision = models.CharField(max_length=8, choices=DatePrecision, blank=True)
    visible = models.BooleanField(default=True)
    notifiable = models.BooleanField(default=True)
    discovered_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["event_date", "date_precision"]),
            models.Index(fields=["visible", "notifiable"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["release_group", "release", "country"],
                condition=models.Q(release__isnull=False),
                name="release_event_unique_group_release_country",
            ),
            models.UniqueConstraint(
                fields=["release_group", "country"],
                condition=models.Q(release__isnull=True),
                name="release_event_unique_group_country_no_release",
            ),
        ]

    def __str__(self) -> str:
        return str(self.release_group)


class Notification(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    release_event = models.ForeignKey(ReleaseEvent, on_delete=models.CASCADE)
    cadence_bucket = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["cadence_bucket", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "release_event", "cadence_bucket"],
                name="notification_unique_user_event_bucket",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} notification for {self.release_event}"


class SyncState(models.Model):
    class SyncType(models.TextChoices):
        ARTIST = "artist", "Artist"
        RELEASES = "releases", "Releases"
        COVER_ART = "cover_art", "Cover art"

    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        STARTED = "started", "Started"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name="sync_states")
    sync_type = models.CharField(max_length=32, choices=SyncType)
    status = models.CharField(max_length=16, choices=Status, default=Status.IDLE)
    last_started_at = models.DateTimeField(null=True, blank=True)
    last_succeeded_at = models.DateTimeField(null=True, blank=True)
    last_failed_at = models.DateTimeField(null=True, blank=True)
    retry_after = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["sync_type", "status"]),
            models.Index(fields=["retry_after"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["artist", "sync_type"],
                name="sync_state_unique_artist_type",
            )
        ]

    def __str__(self) -> str:
        return f"{self.artist} {self.sync_type} sync"


class EmailLog(models.Model):
    class MessageType(models.TextChoices):
        VERIFICATION = "verification", "Verification"
        PASSWORD_RESET = "password_reset", "Password reset"
        DIGEST = "digest", "Digest"
        INSTANT = "instant", "Instant"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    message_type = models.CharField(max_length=32, choices=MessageType)
    status = models.CharField(max_length=16, choices=Status, default=Status.QUEUED)
    provider_message_id = models.CharField(max_length=255, blank=True)
    provider_response = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "message_type", "created_at"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.message_type} email for {self.user}"
