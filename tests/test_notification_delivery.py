from datetime import date
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core import mail

from releasewatch.models import (
    Artist,
    EmailLog,
    Notification,
    ReleaseEvent,
    ReleaseGroup,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def locmem_email_backend(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.DEFAULT_FROM_EMAIL = "muspy@example.test"


def create_user(username="listener", *, email=None):
    return get_user_model().objects.create_user(
        username=username,
        email=email if email is not None else f"{username}@example.test",
        password=None,
    )


def create_notification(user, *, bucket="daily:2026-06-22", title="Repeater"):
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi", sort_name="Fugazi")
    group = ReleaseGroup.objects.create(mbid=uuid4(), artist=artist, title=title)
    event = ReleaseEvent.objects.create(
        release_group=group,
        event_date=date(2026, 6, 22),
    )
    return Notification.objects.create(
        user=user,
        release_event=event,
        cadence_bucket=bucket,
    )


def test_send_pending_notification_emails_sends_digest_and_marks_notifications_sent():
    user = create_user()
    first = create_notification(user, title="Repeater")
    second = create_notification(user, title="End Hits")

    from releasewatch.notification_delivery import send_pending_notification_emails

    result = send_pending_notification_emails(batch_size=10)

    first.refresh_from_db()
    second.refresh_from_db()
    assert result.sent_count == 2
    assert result.failed_count == 0
    assert first.status == Notification.Status.SENT
    assert second.status == Notification.Status.SENT
    assert first.sent_at is not None
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [user.email]
    assert "Repeater" in mail.outbox[0].body
    assert "End Hits" in mail.outbox[0].body
    assert EmailLog.objects.filter(user=user, status=EmailLog.Status.SENT).exists()


def test_send_pending_notification_emails_includes_unsubscribe_url(settings):
    settings.PUBLIC_BASE_URL = "https://muspy.example"
    user = create_user()
    create_notification(user)

    from releasewatch.notification_delivery import send_pending_notification_emails
    from releasewatch.notifications import user_for_unsubscribe_token

    send_pending_notification_emails(batch_size=10)

    body = mail.outbox[0].body
    unsubscribe_line = next(line for line in body.splitlines() if "/email/unsubscribe/" in line)
    token = unsubscribe_line.rsplit("/", 2)[-2]
    assert unsubscribe_line.startswith("Unsubscribe: https://muspy.example/email/unsubscribe/")
    assert user_for_unsubscribe_token(token) == user


def test_send_pending_notification_emails_skips_users_without_email():
    user = create_user(email="")
    notification = create_notification(user)

    from releasewatch.notification_delivery import send_pending_notification_emails

    result = send_pending_notification_emails(batch_size=10)

    notification.refresh_from_db()
    assert result.sent_count == 0
    assert result.skipped_count == 1
    assert notification.status == Notification.Status.SKIPPED
    assert len(mail.outbox) == 0


def test_send_pending_notification_emails_marks_failures(mocker):
    user = create_user()
    notification = create_notification(user)
    mocker.patch("django.core.mail.EmailMessage.send", side_effect=RuntimeError("smtp down"))

    from releasewatch.notification_delivery import send_pending_notification_emails

    result = send_pending_notification_emails(batch_size=10)

    notification.refresh_from_db()
    assert result.sent_count == 0
    assert result.failed_count == 1
    assert notification.status == Notification.Status.FAILED
    assert "smtp down" in notification.error_message
    assert EmailLog.objects.filter(user=user, status=EmailLog.Status.FAILED).exists()


def test_notification_subjects_match_cadence_bucket():
    from releasewatch.notification_delivery import _message_type, _subject

    assert _subject(cadence_bucket="instant:2026-06-22", count=1) == (
        "Muspy release notification"
    )
    assert _subject(cadence_bucket="weekly:2026-W26", count=3) == (
        "Muspy weekly digest (3)"
    )
    assert _message_type("instant:2026-06-22") == EmailLog.MessageType.INSTANT
