# Domain Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tested Django domain models and migrations for users, invites, artists, follows, imports, releases, notifications, feeds, sync state, and email logs.

**Architecture:** Keep all persistent domain models in `releasewatch.models` for this phase so migrations stay simple and reviewable. Use Django 6 `TextChoices`, `JSONField`, `UniqueConstraint`, `CheckConstraint`, and explicit indexes. Do not add upstream clients, sync jobs, views, forms, or feed generation in this plan.

**Tech Stack:** Python 3.14, Django 6, PostgreSQL 18, `pytest`, `pytest-django`, `coverage`, `ruff`, `bandit`.

---

## Scope Check

This plan implements only domain tables, constraints, admin registration, migration files, and model tests. Follow-up plans will add MusicBrainz and import clients, release sync, notification delivery, RSS/iCal generation, and accessible UI.

No legacy code should be copied. The `legacy/` directory remains reference-only.

## Model Decisions

- Store upstream IDs as UUID strings in `UUIDField` where MusicBrainz MBIDs are required.
- Store raw upstream payloads in `models.JSONField(default=dict, blank=True)` only after callers redact credentials, tokens, email addresses, and provider secrets.
- Store incomplete dates as a nullable `DateField` plus a date precision enum.
- Store country as non-null two-character ISO code strings with `blank=True` for unknown country. Do not add a country package in this plan.
- Split `UserProfile` from `NotificationPreference`: profile owns account metadata, preference owns notification settings.
- Use `Follow.is_ignored` to support ignored imported artists without adding a second user-artist table.
- Add `ImportCandidate` even though the design sketch only named `ImportRun`; reviewable imports need per-candidate state.
- Use deterministic HMAC-SHA256 token hashes in `FeedToken`, not plaintext tokens. Token generation will be added in the feed plan.
- Keep one `ReleaseEvent` per release group, concrete release, and country. If MusicBrainz changes the date or precision, sync code updates the existing event instead of creating a second event.

## File Structure

- `releasewatch/models.py`: all domain models and enum choices for this phase.
- `releasewatch/admin.py`: Django admin registrations with list displays and search fields.
- `releasewatch/migrations/0001_initial.py`: generated migration.
- `releasewatch/migrations/__init__.py`: migration package marker.
- `tests/test_domain_models.py`: model defaults, constraints, deletion, and helper behavior.
- `docs/agent-handoff.md`: checkpoint and next-step update after verified commit.

## Checkpoint Policy

- Commit after Task 2, Task 4, Task 6, and Task 8.
- Create local tag `checkpoint/domain-models` after Task 8 passes.
- Update `docs/agent-handoff.md` after checkpoint commits.
- If a task fails badly, add a follow-up fix commit. Do not rewrite existing checkpoint commits.

## Task 1: Add User Profile, Notification Preference, and Feed Token Tests

**Files:**

- Create: `tests/test_domain_models.py`

- [ ] **Step 1: Write failing account model tests**

Create `tests/test_domain_models.py`:

```python
import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from releasewatch.models import (
    FeedToken,
    NotificationCadence,
    NotificationPreference,
    UserProfile,
    redact_payload,
)


pytestmark = pytest.mark.django_db


def create_user(username: str = "user"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="test-password",
    )


def test_user_profile_defaults_and_email_verification_state():
    user = create_user()

    profile = UserProfile.objects.create(user=user)

    assert profile.timezone == "UTC"
    assert profile.country == ""
    assert profile.email_verified_at is None
    assert profile.email_verified is False

    profile.email_verified_at = timezone.now()
    profile.save(update_fields=["email_verified_at"])

    assert profile.email_verified is True


def test_notification_preference_defaults_to_daily_digest():
    user = create_user()

    preference = NotificationPreference.objects.create(user=user)

    assert preference.cadence == NotificationCadence.DAILY
    assert preference.include_future_releases is True
    assert preference.email_enabled is True


def test_notification_preference_rejects_invalid_cadence():
    user = create_user()
    preference = NotificationPreference(user=user, cadence="bad")

    with pytest.raises(ValidationError):
        preference.full_clean()


def test_feed_tokens_are_unique_per_hash_and_scoped_by_user_and_type():
    user = create_user()

    FeedToken.objects.create(
        user=user,
        feed_type=FeedToken.FeedType.RSS,
        token_hash="a" * 64,
    )

    with pytest.raises(IntegrityError):
        FeedToken.objects.create(
            user=user,
            feed_type=FeedToken.FeedType.ICAL,
            token_hash="a" * 64,
        )


def test_redact_payload_removes_sensitive_values_recursively():
    payload = {
        "artist": "Example",
        "email": "person@example.test",
        "nested": {
            "access_token": "secret-token",
            "client_secret": "secret-client",
            "safe": "kept",
        },
        "items": [{"api_key": "secret-key"}],
    }

    redacted = redact_payload(payload)

    assert redacted == {
        "artist": "Example",
        "email": "[redacted]",
        "nested": {
            "access_token": "[redacted]",
            "client_secret": "[redacted]",
            "safe": "kept",
        },
        "items": [{"api_key": "[redacted]"}],
    }
```

- [ ] **Step 2: Run tests to verify red**

Run:

```powershell
$env:DEBUG='1'; $env:SECRET_KEY='domain-test-secret'; $env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-domain.sqlite3'; uv run pytest tests/test_domain_models.py -q
```

Expected: fails because `FeedToken`, `NotificationCadence`, `NotificationPreference`, and `UserProfile` do not exist.

## Task 2: Implement Account Models and Checkpoint

**Files:**

- Modify: `releasewatch/models.py`
- Create: `releasewatch/migrations/__init__.py`
- Generate: `releasewatch/migrations/0001_initial.py`
- Modify: `docs/agent-handoff.md`

- [ ] **Step 1: Implement account models**

Create or replace `releasewatch/models.py` with:

```python
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

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None

    def __str__(self) -> str:
        return f"Profile for {self.user}"


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

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def __str__(self) -> str:
        return f"{self.feed_type} token for {self.user}"
```

- [ ] **Step 2: Create migration package and migration**

Run:

```powershell
New-Item -ItemType Directory -Force -Path releasewatch/migrations | Out-Null
New-Item -ItemType File -Force -Path releasewatch/migrations/__init__.py | Out-Null
$env:DEBUG='1'; $env:SECRET_KEY='domain-test-secret'; uv run python manage.py makemigrations releasewatch
```

Expected: `releasewatch/migrations/0001_initial.py` is created.

- [ ] **Step 3: Run account tests to verify green**

Run:

```powershell
$env:DEBUG='1'; $env:SECRET_KEY='domain-test-secret'; $env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-domain.sqlite3'; uv run pytest tests/test_domain_models.py -q
```

Expected: 5 tests pass.

- [ ] **Step 4: Run migration check**

Run:

```powershell
$env:DEBUG='1'; $env:SECRET_KEY='domain-test-secret'; $env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-domain.sqlite3'; uv run python manage.py migrate --noinput
```

Expected: all migrations apply.

- [ ] **Step 5: Commit checkpoint**

Run:

```powershell
Remove-Item .tmp-domain.sqlite3* -ErrorAction SilentlyContinue
git add releasewatch/models.py releasewatch/migrations tests/test_domain_models.py
git commit -m "feat: add account domain models"
git rev-parse --short HEAD
```

Expected: commit succeeds.

## Task 3: Add Invite, Artist, Follow, and Import Tests

**Files:**

- Modify: `tests/test_domain_models.py`

- [ ] **Step 1: Update imports and add failing invite and artist tests**

First update the import block at the top of `tests/test_domain_models.py`:

```python
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from releasewatch.models import (
    Artist,
    ArtistAlias,
    FeedToken,
    Follow,
    ImportCandidate,
    ImportRun,
    Invite,
    NotificationCadence,
    NotificationPreference,
    UserProfile,
    redact_payload,
)
```

Then append to `tests/test_domain_models.py`:

```python


def test_invite_tracks_uses_and_expiration():
    creator = create_user("creator")
    invite = Invite.objects.create(
        code="abc123",
        created_by=creator,
        max_uses=2,
        expires_at=timezone.now() + timezone.timedelta(days=1),
    )

    assert invite.can_be_used is True

    invite.uses = 2
    invite.save(update_fields=["uses"])

    assert invite.can_be_used is False

    with pytest.raises(IntegrityError):
        Invite.objects.create(code="overused", max_uses=2, uses=3)


def test_artist_mbid_is_unique_and_aliases_order_by_locale_then_name():
    artist = Artist.objects.create(
        mbid=uuid4(),
        name="The Example",
        sort_name="Example, The",
    )
    ArtistAlias.objects.create(artist=artist, name="Example", locale="en")
    ArtistAlias.objects.create(artist=artist, name="Ejemplo", locale="es")

    assert list(artist.aliases.values_list("locale", "name")) == [
        ("en", "Example"),
        ("es", "Ejemplo"),
    ]

    with pytest.raises(IntegrityError):
        Artist.objects.create(mbid=artist.mbid, name="Duplicate")


def test_follow_is_unique_per_user_artist_and_can_track_ignored_artist():
    user = create_user("listener")
    artist = Artist.objects.create(mbid=uuid4(), name="Artist")

    Follow.objects.create(user=user, artist=artist, is_ignored=True)

    with pytest.raises(IntegrityError):
        Follow.objects.create(user=user, artist=artist)


def test_import_run_and_candidates_store_review_state():
    user = create_user("importer")
    artist = Artist.objects.create(mbid=uuid4(), name="Imported Artist")
    run = ImportRun.objects.create(
        user=user,
        source=ImportRun.Source.LASTFM,
        status=ImportRun.Status.PENDING_REVIEW,
        raw_payload={"artists": ["Imported Artist"]},
    )

    candidate = ImportCandidate.objects.create(
        import_run=run,
        artist=artist,
        source_name="Imported Artist",
        source_identifier="lastfm:imported-artist",
        review_state=ImportCandidate.ReviewState.PENDING,
    )

    assert candidate.review_state == ImportCandidate.ReviewState.PENDING
    assert run.raw_payload["artists"] == ["Imported Artist"]


def test_import_candidates_allow_multiple_blank_source_identifiers():
    user = create_user("plain-text-importer")
    run = ImportRun.objects.create(
        user=user,
        source=ImportRun.Source.PLAIN_TEXT,
        status=ImportRun.Status.PENDING_REVIEW,
    )

    ImportCandidate.objects.create(import_run=run, source_name="First")
    ImportCandidate.objects.create(import_run=run, source_name="Second")

    assert run.candidates.count() == 2
```

- [ ] **Step 2: Run new tests to verify red**

Run:

```powershell
$env:DEBUG='1'; $env:SECRET_KEY='domain-test-secret'; $env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-domain.sqlite3'; uv run pytest tests/test_domain_models.py -q
```

Expected: fails because invite, artist, follow, and import models do not exist.

## Task 4: Implement Invite, Artist, Follow, and Import Models

**Files:**

- Modify: `releasewatch/models.py`
- Generate: `releasewatch/migrations/0002_invites_artists_imports.py`

- [ ] **Step 1: Append models**

Append to `releasewatch/models.py`:

```python
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

    @property
    def can_be_used(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= timezone.now():
            return False
        return self.uses < self.max_uses

    def __str__(self) -> str:
        return self.code


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

    import_run = models.ForeignKey(ImportRun, on_delete=models.CASCADE, related_name="candidates")
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
```

Also add this import near the top of `releasewatch/models.py`:

```python
from django.utils import timezone
```

- [ ] **Step 2: Generate migration**

Run:

```powershell
$env:DEBUG='1'; $env:SECRET_KEY='domain-test-secret'; uv run python manage.py makemigrations releasewatch --name invites_artists_imports
```

Expected: migration `0002_invites_artists_imports.py` is created.

- [ ] **Step 3: Run tests**

Run:

```powershell
$env:DEBUG='1'; $env:SECRET_KEY='domain-test-secret'; $env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-domain.sqlite3'; uv run pytest tests/test_domain_models.py -q
```

Expected: all domain model tests pass.

- [ ] **Step 4: Commit checkpoint**

Run:

```powershell
Remove-Item .tmp-domain.sqlite3* -ErrorAction SilentlyContinue
git add releasewatch/models.py releasewatch/migrations tests/test_domain_models.py
git commit -m "feat: add artist and import domain models"
git rev-parse --short HEAD
```

Expected: commit succeeds.

## Task 5: Add Release, Notification, Sync, and Email Tests

**Files:**

- Modify: `tests/test_domain_models.py`

- [ ] **Step 1: Update imports and add failing release and notification tests**

First update the import block at the top of `tests/test_domain_models.py`:

```python
from datetime import date
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from releasewatch.models import (
    Artist,
    ArtistAlias,
    DatePrecision,
    EmailLog,
    FeedToken,
    Follow,
    ImportCandidate,
    ImportRun,
    Invite,
    Notification,
    NotificationCadence,
    NotificationPreference,
    Release,
    ReleaseEvent,
    ReleaseGroup,
    SyncState,
    UserProfile,
    redact_payload,
)
```

Then append to `tests/test_domain_models.py`:

```python


def test_release_group_stores_incomplete_date_with_precision():
    artist = Artist.objects.create(mbid=uuid4(), name="Artist")
    group = ReleaseGroup.objects.create(
        mbid=uuid4(),
        artist=artist,
        title="Future Album",
        primary_type="Album",
        first_release_date=date(2026, 6, 1),
        first_release_precision=DatePrecision.MONTH,
    )

    assert group.first_release_precision == DatePrecision.MONTH
    assert str(group) == "Artist - Future Album"


def test_release_is_unique_by_mbid_and_country_date_is_queryable():
    artist = Artist.objects.create(mbid=uuid4(), name="Artist")
    group = ReleaseGroup.objects.create(mbid=uuid4(), artist=artist, title="Album")
    release = Release.objects.create(
        mbid=uuid4(),
        release_group=group,
        country="US",
        release_date=date(2026, 6, 21),
        release_date_precision=DatePrecision.DAY,
    )

    assert release.country == "US"

    with pytest.raises(IntegrityError):
        Release.objects.create(mbid=release.mbid, release_group=group)


def test_release_event_dedupes_release_group_release_country():
    artist = Artist.objects.create(mbid=uuid4(), name="Artist")
    group = ReleaseGroup.objects.create(mbid=uuid4(), artist=artist, title="Album")
    release = Release.objects.create(mbid=uuid4(), release_group=group, country="US")

    ReleaseEvent.objects.create(
        release_group=group,
        release=release,
        country="US",
        event_date=date(2026, 6, 21),
        date_precision=DatePrecision.DAY,
    )

    with pytest.raises(IntegrityError):
        ReleaseEvent.objects.create(
            release_group=group,
            release=release,
            country="US",
            event_date=date(2026, 6, 21),
            date_precision=DatePrecision.DAY,
        )


def test_release_event_dedupes_release_group_country_without_concrete_release():
    artist = Artist.objects.create(mbid=uuid4(), name="Artist")
    group = ReleaseGroup.objects.create(mbid=uuid4(), artist=artist, title="Album")

    ReleaseEvent.objects.create(
        release_group=group,
        country="US",
        event_date=date(2026, 6, 21),
        date_precision=DatePrecision.DAY,
    )

    with pytest.raises(IntegrityError):
        ReleaseEvent.objects.create(
            release_group=group,
            country="US",
            event_date=date(2026, 6, 21),
            date_precision=DatePrecision.DAY,
        )


def test_notification_dedupes_user_event_and_bucket():
    user = create_user("notify")
    artist = Artist.objects.create(mbid=uuid4(), name="Artist")
    group = ReleaseGroup.objects.create(mbid=uuid4(), artist=artist, title="Album")
    event = ReleaseEvent.objects.create(release_group=group)

    Notification.objects.create(
        user=user,
        release_event=event,
        cadence_bucket="daily:2026-06-21",
    )

    with pytest.raises(IntegrityError):
        Notification.objects.create(
            user=user,
            release_event=event,
            cadence_bucket="daily:2026-06-21",
        )


def test_sync_state_and_email_log_store_retry_and_provider_metadata():
    user = create_user("email")
    artist = Artist.objects.create(mbid=uuid4(), name="Artist")

    sync_state = SyncState.objects.create(
        artist=artist,
        sync_type=SyncState.SyncType.RELEASES,
        status=SyncState.Status.FAILED,
        retry_after=timezone.now(),
        error_message="rate limited",
    )
    log = EmailLog.objects.create(
        user=user,
        message_type=EmailLog.MessageType.DIGEST,
        status=EmailLog.Status.FAILED,
        provider_response={"code": "421"},
        error_message="temporary failure",
    )

    assert sync_state.status == SyncState.Status.FAILED
    assert log.provider_response["code"] == "421"


def test_user_deletion_removes_user_owned_domain_records():
    user = create_user("delete-me")
    artist = Artist.objects.create(mbid=uuid4(), name="Artist")
    group = ReleaseGroup.objects.create(mbid=uuid4(), artist=artist, title="Album")
    event = ReleaseEvent.objects.create(release_group=group)
    import_run = ImportRun.objects.create(user=user, source=ImportRun.Source.PLAIN_TEXT)

    UserProfile.objects.create(user=user)
    NotificationPreference.objects.create(user=user)
    FeedToken.objects.create(
        user=user,
        feed_type=FeedToken.FeedType.RSS,
        token_hash="b" * 64,
    )
    Follow.objects.create(user=user, artist=artist)
    ImportCandidate.objects.create(import_run=import_run, artist=artist, source_name="Artist")
    Notification.objects.create(user=user, release_event=event, cadence_bucket="daily:2026-06-21")
    EmailLog.objects.create(user=user, message_type=EmailLog.MessageType.DIGEST)

    user.delete()

    assert UserProfile.objects.count() == 0
    assert NotificationPreference.objects.count() == 0
    assert FeedToken.objects.count() == 0
    assert Follow.objects.count() == 0
    assert ImportRun.objects.count() == 0
    assert ImportCandidate.objects.count() == 0
    assert Notification.objects.count() == 0
    assert EmailLog.objects.count() == 0
    assert Artist.objects.count() == 1
    assert ReleaseEvent.objects.count() == 1
```

- [ ] **Step 2: Run tests to verify red**

Run:

```powershell
$env:DEBUG='1'; $env:SECRET_KEY='domain-test-secret'; $env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-domain.sqlite3'; uv run pytest tests/test_domain_models.py -q
```

Expected: fails because release, notification, sync, and email models do not exist.

## Task 6: Implement Release, Notification, Sync, and Email Models

**Files:**

- Modify: `releasewatch/models.py`
- Generate: `releasewatch/migrations/0003_releases_notifications_sync.py`

- [ ] **Step 1: Append release and operational models**

Append to `releasewatch/models.py`:

```python
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
            )
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
```

- [ ] **Step 2: Generate migration**

Run:

```powershell
$env:DEBUG='1'; $env:SECRET_KEY='domain-test-secret'; uv run python manage.py makemigrations releasewatch --name releases_notifications_sync
```

Expected: migration `0003_releases_notifications_sync.py` is created.

- [ ] **Step 3: Run domain tests**

Run:

```powershell
$env:DEBUG='1'; $env:SECRET_KEY='domain-test-secret'; $env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-domain.sqlite3'; uv run pytest tests/test_domain_models.py -q
```

Expected: all domain model tests pass.

- [ ] **Step 4: Commit checkpoint**

Run:

```powershell
Remove-Item .tmp-domain.sqlite3* -ErrorAction SilentlyContinue
git add releasewatch/models.py releasewatch/migrations tests/test_domain_models.py
git commit -m "feat: add release and notification domain models"
git rev-parse --short HEAD
```

Expected: commit succeeds.

## Task 7: Add Admin Registration and Full Verification

**Files:**

- Create: `releasewatch/admin.py`
- Modify: `tests/test_domain_models.py`

- [ ] **Step 1: Update imports and add failing admin registration test**

First add this import near the other Django imports at the top of `tests/test_domain_models.py`:

```python
from django.contrib import admin
```

Then append to `tests/test_domain_models.py`:

```python

def test_domain_models_are_registered_in_admin():
    registered_models = set(admin.site._registry)

    assert UserProfile in registered_models
    assert NotificationPreference in registered_models
    assert FeedToken in registered_models
    assert Invite in registered_models
    assert Artist in registered_models
    assert ArtistAlias in registered_models
    assert Follow in registered_models
    assert ImportRun in registered_models
    assert ImportCandidate in registered_models
    assert ReleaseGroup in registered_models
    assert Release in registered_models
    assert ReleaseEvent in registered_models
    assert Notification in registered_models
    assert SyncState in registered_models
    assert EmailLog in registered_models
```

- [ ] **Step 2: Run admin test to verify red**

Run:

```powershell
$env:DEBUG='1'; $env:SECRET_KEY='domain-test-secret'; $env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-domain.sqlite3'; uv run pytest tests/test_domain_models.py::test_domain_models_are_registered_in_admin -q
```

Expected: fails because models are not registered.

- [ ] **Step 3: Register models in admin**

Create `releasewatch/admin.py`:

```python
from django.contrib import admin

from .models import (
    Artist,
    ArtistAlias,
    EmailLog,
    FeedToken,
    Follow,
    ImportCandidate,
    ImportRun,
    Invite,
    Notification,
    NotificationPreference,
    Release,
    ReleaseEvent,
    ReleaseGroup,
    SyncState,
    UserProfile,
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "timezone", "country", "email_verified_at"]
    search_fields = ["user__username", "user__email"]


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ["user", "cadence", "email_enabled", "include_future_releases"]
    list_filter = ["cadence", "email_enabled", "include_future_releases"]
    search_fields = ["user__username", "user__email"]


@admin.register(FeedToken)
class FeedTokenAdmin(admin.ModelAdmin):
    list_display = ["user", "feed_type", "name", "revoked_at", "last_used_at"]
    list_filter = ["feed_type", "revoked_at"]
    search_fields = ["user__username", "user__email", "name"]


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ["code", "created_by", "uses", "max_uses", "expires_at", "revoked_at"]
    search_fields = ["code", "created_by__username"]


class ArtistAliasInline(admin.TabularInline):
    model = ArtistAlias
    extra = 0


@admin.register(Artist)
class ArtistAdmin(admin.ModelAdmin):
    list_display = ["name", "sort_name", "country", "last_refreshed_at"]
    search_fields = ["name", "sort_name", "mbid"]
    list_filter = ["artist_type", "country"]
    inlines = [ArtistAliasInline]


@admin.register(ArtistAlias)
class ArtistAliasAdmin(admin.ModelAdmin):
    list_display = ["artist", "name", "locale", "primary"]
    search_fields = ["name", "artist__name"]
    list_filter = ["locale", "primary"]


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ["user", "artist", "is_ignored", "created_at"]
    list_filter = ["is_ignored"]
    search_fields = ["user__username", "artist__name"]


@admin.register(ImportRun)
class ImportRunAdmin(admin.ModelAdmin):
    list_display = ["user", "source", "status", "created_at", "updated_at"]
    list_filter = ["source", "status"]
    search_fields = ["user__username"]


@admin.register(ImportCandidate)
class ImportCandidateAdmin(admin.ModelAdmin):
    list_display = ["source_name", "artist", "review_state", "created_at", "reviewed_at"]
    list_filter = ["review_state"]
    search_fields = ["source_name", "source_identifier", "artist__name"]


@admin.register(ReleaseGroup)
class ReleaseGroupAdmin(admin.ModelAdmin):
    list_display = ["title", "artist", "primary_type", "first_release_date"]
    search_fields = ["title", "artist__name", "mbid"]
    list_filter = ["primary_type"]


@admin.register(Release)
class ReleaseAdmin(admin.ModelAdmin):
    list_display = ["release_group", "country", "release_date", "status"]
    search_fields = ["release_group__title", "mbid"]
    list_filter = ["country", "status"]


@admin.register(ReleaseEvent)
class ReleaseEventAdmin(admin.ModelAdmin):
    list_display = ["release_group", "release", "country", "event_date", "visible", "notifiable"]
    list_filter = ["visible", "notifiable", "date_precision"]
    search_fields = ["release_group__title", "release__mbid"]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["user", "release_event", "cadence_bucket", "status", "sent_at", "failed_at"]
    list_filter = ["status"]
    search_fields = ["user__username", "release_event__release_group__title"]


@admin.register(SyncState)
class SyncStateAdmin(admin.ModelAdmin):
    list_display = ["artist", "sync_type", "status", "retry_after", "updated_at"]
    list_filter = ["sync_type", "status"]
    search_fields = ["artist__name"]


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ["user", "message_type", "status", "created_at", "sent_at"]
    list_filter = ["message_type", "status"]
    search_fields = ["user__username", "provider_message_id"]
```

- [ ] **Step 4: Run domain tests**

Run:

```powershell
$env:DEBUG='1'; $env:SECRET_KEY='domain-test-secret'; $env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-domain.sqlite3'; uv run pytest tests/test_domain_models.py -q
```

Expected: all domain model tests pass.

- [ ] **Step 5: Run full local verification**

Run:

```powershell
$env:SECRET_KEY='domain-test-secret'; uv run pytest tests/test_settings_security.py -q
$env:DEBUG='1'; $env:SECRET_KEY='domain-test-secret'; $env:DATABASE_URL='sqlite:///C:/Users/blind/gitrepos/muspy/.tmp-domain.sqlite3'; uv run coverage run -m pytest tests/test_domain_models.py tests/test_dev_admin_command.py tests/test_project_smoke.py tests/test_container_files.py tests/test_ci_workflow.py -q
uv run coverage report
uv run ruff check .
uv run bandit -c pyproject.toml -r config releasewatch
uv run python manage.py check
Remove-Item .tmp-domain.sqlite3* -ErrorAction SilentlyContinue
```

Expected:

- tests pass
- coverage remains at or above 85%
- lint passes
- Bandit reports no issues
- Django check reports no issues

## Task 8: Final Handoff, Checkpoint, and Tag

**Files:**

- Modify: `docs/agent-handoff.md`

- [ ] **Step 1: Update handoff**

Update `docs/agent-handoff.md`:

```markdown
## Current Phase

Domain models complete.

## Last Known Good Commit

- Add the short hash from Task 7 followed by `domain models verified`.

## Next Required Step

Write and review the upstream client implementation plan before adding MusicBrainz, ListenBrainz, or Last.fm clients.
```

- [ ] **Step 2: Commit checkpoint**

Run:

```powershell
git add releasewatch/models.py releasewatch/admin.py releasewatch/migrations tests/test_domain_models.py docs/agent-handoff.md
git commit -m "feat: add domain model foundation"
git rev-parse --short HEAD
```

Expected: commit succeeds.

- [ ] **Step 3: Create checkpoint tag**

Run:

```powershell
git tag checkpoint/domain-models
```

Expected: tag exists locally.

- [ ] **Step 4: Verify final state**

Run:

```powershell
git status --short --branch --untracked-files=all
git log --oneline -8
git tag --list 'checkpoint/*'
```

Expected:

- worktree clean
- recent log includes domain model checkpoint commits
- tags include `checkpoint/domain-models`

## Follow-up Plans After This File

Write separate plans before implementation for:

1. Upstream MusicBrainz, ListenBrainz, and Last.fm clients.
2. Import and follow workflows.
3. Release sync and sync explainability.
4. Notification batching and email delivery.
5. RSS and iCal feeds.
6. Accessible UI.
7. Security and deployment hardening beyond the foundation.

Each follow-up plan must use TDD, include rollback checkpoints, and update `docs/agent-handoff.md`.
