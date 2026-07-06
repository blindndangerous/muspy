from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth import get_user_model
from django.core import signing
from django.utils import timezone

from releasewatch.models import (
    Follow,
    Notification,
    NotificationCadence,
    ReleaseEvent,
)

_EMAIL_LINK_SALT = "releasewatch.email-links"
_PURPOSE_UNSUBSCRIBE = "notification-unsubscribe"
_PURPOSE_EMAIL_VERIFICATION = "email-verification"
_EMAIL_VERIFICATION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
_RELEASE_TYPE_FIELD_BY_VALUE = {
    "album": "include_albums",
    "single": "include_singles",
    "ep": "include_eps",
    "live": "include_live",
    "compilation": "include_compilations",
    "remix": "include_remixes",
}
_OTHER_RELEASE_TYPE_FIELD = "include_other_release_types"


class InvalidEmailLinkToken(ValueError):
    pass


@dataclass(frozen=True)
class NotificationFanoutResult:
    release_event: ReleaseEvent
    created_count: int = 0
    existing_count: int = 0
    skipped_count: int = 0


@dataclass(frozen=True)
class _DefaultPreference:
    cadence: str = NotificationCadence.DAILY
    email_enabled: bool = True
    include_future_releases: bool = True
    include_albums: bool = True
    include_singles: bool = True
    include_eps: bool = True
    include_live: bool = True
    include_compilations: bool = True
    include_remixes: bool = True
    include_other_release_types: bool = True


def make_unsubscribe_token(user) -> str:
    return _make_email_link_token(user=user, purpose=_PURPOSE_UNSUBSCRIBE)


def user_for_unsubscribe_token(token: str):
    return _user_for_email_link_token(token=token, purpose=_PURPOSE_UNSUBSCRIBE)


def make_email_verification_token(user) -> str:
    return _make_email_link_token(
        user=user,
        purpose=_PURPOSE_EMAIL_VERIFICATION,
        email=user.email,
    )


def user_for_email_verification_token(token: str):
    return _user_for_email_link_token(
        token=token,
        purpose=_PURPOSE_EMAIL_VERIFICATION,
        max_age=_EMAIL_VERIFICATION_MAX_AGE_SECONDS,
        require_current_email=True,
    )


def fanout_release_event_notifications(
    *,
    release_event: ReleaseEvent,
    now: datetime | None = None,
) -> NotificationFanoutResult:
    now = now or timezone.now()
    candidates: list[tuple[int, str]] = []
    skipped_count = 0
    follows = (
        Follow.objects.select_related("user", "user__notificationpreference")
        .filter(artist=release_event.release_group.artist)
        .order_by("user_id")
    )

    for follow in follows:
        if follow.is_ignored or not release_event.notifiable:
            skipped_count += 1
            continue
        preference = _preference_for_user(follow.user)
        if _preference_skips_event(
            preference=preference,
            release_event=release_event,
            now=now,
        ):
            skipped_count += 1
            continue
        candidates.append(
            (
                follow.user_id,
                _cadence_bucket(
                    cadence=preference.cadence,
                    release_event=release_event,
                    now=now,
                ),
            )
        )

    existing_keys = _existing_notification_keys(
        release_event=release_event,
        candidates=candidates,
    )
    new_notifications = [
        Notification(
            user_id=user_id,
            release_event=release_event,
            cadence_bucket=cadence_bucket,
            status=Notification.Status.PENDING,
        )
        for user_id, cadence_bucket in candidates
        if (user_id, cadence_bucket) not in existing_keys
    ]
    Notification.objects.bulk_create(new_notifications, ignore_conflicts=True)
    return NotificationFanoutResult(
        release_event=release_event,
        created_count=len(new_notifications),
        existing_count=len(candidates) - len(new_notifications),
        skipped_count=skipped_count,
    )


def _make_email_link_token(*, user, purpose: str, email: str = "") -> str:
    payload = {"purpose": purpose, "user_id": user.pk}
    if email:
        payload["email"] = email
    return signing.dumps(payload, salt=_EMAIL_LINK_SALT)


def _user_for_email_link_token(
    *,
    token: str,
    purpose: str,
    max_age: int | None = None,
    require_current_email: bool = False,
):
    try:
        payload = signing.loads(token, salt=_EMAIL_LINK_SALT, max_age=max_age)
    except signing.BadSignature as error:
        raise InvalidEmailLinkToken("Invalid email link token.") from error
    if not isinstance(payload, dict) or payload.get("purpose") != purpose:
        raise InvalidEmailLinkToken("Invalid email link token.")

    user_id = payload.get("user_id")
    if user_id is None:
        raise InvalidEmailLinkToken("Invalid email link token.")

    filters = {"pk": user_id}
    if require_current_email:
        filters["email"] = payload.get("email", "")
    try:
        return get_user_model().objects.get(**filters)
    except get_user_model().DoesNotExist as error:
        raise InvalidEmailLinkToken("Invalid email link token.") from error


def _preference_for_user(user):
    return getattr(user, "notificationpreference", None) or _DefaultPreference()


def _preference_skips_event(
    *,
    preference,
    release_event: ReleaseEvent,
    now: datetime,
) -> bool:
    if not preference.email_enabled or preference.cadence == NotificationCadence.OFF:
        return True
    if (
        not preference.include_future_releases
        and release_event.event_date is not None
        and release_event.event_date > now.date()
    ):
        return True
    return _preference_disables_release_type(
        preference=preference,
        release_event=release_event,
    )


def _preference_disables_release_type(*, preference, release_event: ReleaseEvent) -> bool:
    return any(
        not getattr(preference, field_name, True)
        for field_name in _release_type_filter_fields(release_event)
    )


def _release_type_filter_fields(release_event: ReleaseEvent) -> set[str]:
    release_group = release_event.release_group
    type_values = [release_group.primary_type, *_secondary_type_values(release_group)]
    return {_release_type_filter_field(type_value) for type_value in type_values}


def _secondary_type_values(release_group) -> list[str]:
    secondary_types = release_group.secondary_types
    if isinstance(secondary_types, list):
        return secondary_types
    return []


def _release_type_filter_field(type_value) -> str:
    normalized = str(type_value or "").strip().casefold()
    return _RELEASE_TYPE_FIELD_BY_VALUE.get(normalized, _OTHER_RELEASE_TYPE_FIELD)


def _cadence_bucket(*, cadence: str, release_event: ReleaseEvent, now: datetime) -> str:
    if cadence == NotificationCadence.INSTANT:
        return f"instant:{release_event.id}"
    if cadence == NotificationCadence.WEEKLY:
        iso_year, iso_week, _ = now.isocalendar()
        return f"weekly:{iso_year}-W{iso_week:02d}"
    return f"daily:{now.date().isoformat()}"


def _existing_notification_keys(
    *,
    release_event: ReleaseEvent,
    candidates: list[tuple[int, str]],
) -> set[tuple[int, str]]:
    if not candidates:
        return set()
    user_ids = {user_id for user_id, _ in candidates}
    cadence_buckets = {cadence_bucket for _, cadence_bucket in candidates}
    return set(
        Notification.objects.filter(
            release_event=release_event,
            user_id__in=user_ids,
            cadence_bucket__in=cadence_buckets,
        ).values_list("user_id", "cadence_bucket")
    )
