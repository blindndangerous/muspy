from dataclasses import dataclass

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from releasewatch.models import EmailLog, Notification
from releasewatch.notifications import make_unsubscribe_token


@dataclass(frozen=True)
class NotificationDeliveryResult:
    sent_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0


def send_pending_notification_emails(*, batch_size: int = 100) -> NotificationDeliveryResult:
    groups = _pending_groups(batch_size=batch_size)
    sent_count = 0
    failed_count = 0
    skipped_count = 0

    for user_id, cadence_bucket in groups:
        notifications = list(_pending_notifications(user_id=user_id, cadence_bucket=cadence_bucket))
        if not notifications:
            continue
        user = notifications[0].user
        if not user.email:
            _mark_notifications(notifications, status=Notification.Status.SKIPPED)
            skipped_count += len(notifications)
            continue
        try:
            _send_notification_group(
                user=user,
                cadence_bucket=cadence_bucket,
                notifications=notifications,
            )
        except Exception as error:
            _mark_notifications(
                notifications,
                status=Notification.Status.FAILED,
                error_message=str(error),
            )
            EmailLog.objects.create(
                user=user,
                message_type=_message_type(cadence_bucket),
                status=EmailLog.Status.FAILED,
                error_message=str(error),
            )
            failed_count += len(notifications)
            continue
        _mark_notifications(notifications, status=Notification.Status.SENT)
        EmailLog.objects.create(
            user=user,
            message_type=_message_type(cadence_bucket),
            status=EmailLog.Status.SENT,
            sent_at=timezone.now(),
        )
        sent_count += len(notifications)

    return NotificationDeliveryResult(
        sent_count=sent_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
    )


def _pending_groups(*, batch_size: int) -> list[tuple[int, str]]:
    return list(
        Notification.objects.filter(status=Notification.Status.PENDING)
        .order_by("created_at", "id")
        .values_list("user_id", "cadence_bucket")
        .distinct()[:batch_size]
    )


def _pending_notifications(*, user_id: int, cadence_bucket: str):
    return (
        Notification.objects.select_related(
            "user",
            "release_event__release_group__artist",
        )
        .filter(
            user_id=user_id,
            cadence_bucket=cadence_bucket,
            status=Notification.Status.PENDING,
        )
        .order_by("release_event__event_date", "release_event__release_group__title", "id")
    )


def _send_notification_group(
    *,
    user,
    cadence_bucket: str,
    notifications: list[Notification],
) -> None:
    subject = _subject(cadence_bucket=cadence_bucket, count=len(notifications))
    body = "\n".join(
        [
            "New releases for artists you follow:",
            "",
            *[_notification_line(notification) for notification in notifications],
            "",
            "Change notification settings in Muspy.",
            f"Unsubscribe: {_unsubscribe_url(user)}",
        ]
    )
    EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    ).send(fail_silently=False)


def _mark_notifications(
    notifications: list[Notification],
    *,
    status: str,
    error_message: str = "",
) -> None:
    now = timezone.now()
    with transaction.atomic():
        for notification in notifications:
            notification.status = status
            notification.error_message = error_message
            update_fields = ["status", "error_message"]
            if status == Notification.Status.SENT:
                notification.sent_at = now
                update_fields.append("sent_at")
            elif status == Notification.Status.FAILED:
                notification.failed_at = now
                update_fields.append("failed_at")
            notification.save(update_fields=update_fields)


def _notification_line(notification: Notification) -> str:
    event = notification.release_event
    date_text = event.event_date.isoformat() if event.event_date else "Unknown date"
    return f"- {event.release_group.artist.name} - {event.release_group.title} ({date_text})"


def _unsubscribe_url(user) -> str:
    path = reverse("releasewatch:email_unsubscribe", args=[make_unsubscribe_token(user)])
    return f"{_public_base_url()}{path}"


def _public_base_url() -> str:
    return getattr(settings, "PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


def _subject(*, cadence_bucket: str, count: int) -> str:
    if cadence_bucket.startswith("instant:"):
        return "Muspy release notification"
    if cadence_bucket.startswith("weekly:"):
        return f"Muspy weekly digest ({count})"
    return f"Muspy daily digest ({count})"


def _message_type(cadence_bucket: str) -> str:
    if cadence_bucket.startswith("instant:"):
        return EmailLog.MessageType.INSTANT
    return EmailLog.MessageType.DIGEST
