import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache, caches
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from releasewatch.models import EmailLog, UserProfile

pytestmark = pytest.mark.django_db
TEST_PASSWORD = "test-password"  # noqa: S105


@pytest.fixture(autouse=True)
def locmem_backends(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "email-verification-request-tests",
        }
    }
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.DEFAULT_FROM_EMAIL = "muspy@example.test"
    settings.PUBLIC_BASE_URL = "https://muspy.example"
    caches.close_all()
    cache.clear()
    yield
    cache.clear()
    caches.close_all()


def create_user(username="listener"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password=TEST_PASSWORD,
    )


def login_unverified_user(client):
    user = create_user()
    UserProfile.objects.create(user=user, email_verified_at=None)
    client.force_login(user)
    return user


def test_unverified_user_can_resend_email_verification(client):
    user = login_unverified_user(client)

    response = client.post(reverse("releasewatch:resend_email_verification"))

    assert response.status_code == 302
    assert response["Location"] == reverse("releasewatch:account_settings")
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == [user.email]
    assert "Verify your Muspy email address" == message.subject
    assert "https://muspy.example/email/verify/" in message.body
    assert EmailLog.objects.filter(
        user=user,
        message_type=EmailLog.MessageType.VERIFICATION,
        status=EmailLog.Status.SENT,
    ).exists()


def test_verified_user_resend_is_noop_without_sending_email(client):
    user = create_user()
    UserProfile.objects.create(user=user, email_verified_at=timezone.now())
    client.force_login(user)

    response = client.post(reverse("releasewatch:resend_email_verification"), follow=True)

    assert response.status_code == 200
    assert len(mail.outbox) == 0
    assert "already verified" in response.content.decode().lower()
    assert not EmailLog.objects.filter(
        user=user,
        message_type=EmailLog.MessageType.VERIFICATION,
    ).exists()


@override_settings(RATE_LIMIT_EMAIL_VERIFICATION_RESEND=(1, 60))
def test_verified_user_resend_noop_does_not_trigger_rate_limit(client):
    user = create_user()
    UserProfile.objects.create(user=user, email_verified_at=timezone.now())
    client.force_login(user)
    url = reverse("releasewatch:resend_email_verification")

    first_response = client.post(url, follow=True)
    second_response = client.post(url, follow=True)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert "already verified" in second_response.content.decode().lower()
    assert len(mail.outbox) == 0


def test_resend_email_verification_is_post_only_for_authenticated_users(client):
    login_unverified_user(client)

    response = client.get(reverse("releasewatch:resend_email_verification"))

    assert response.status_code == 405
    assert response["Allow"] == "POST"
    assert len(mail.outbox) == 0


def test_resend_email_verification_requires_login(client):
    response = client.post(reverse("releasewatch:resend_email_verification"))

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]
    assert len(mail.outbox) == 0


@override_settings(RATE_LIMIT_EMAIL_VERIFICATION_RESEND=(1, 60))
def test_resend_email_verification_rate_limits_excessive_requests(client):
    login_unverified_user(client)
    url = reverse("releasewatch:resend_email_verification")

    first_response = client.post(url)
    second_response = client.post(url)

    assert first_response.status_code == 302
    assert second_response.status_code == 429
    assert second_response["Retry-After"]
    assert len(mail.outbox) == 1


def test_resend_email_verification_email_token_validates_current_user(client):
    user = login_unverified_user(client)

    client.post(reverse("releasewatch:resend_email_verification"))

    body = mail.outbox[0].body
    verify_line = next(line for line in body.splitlines() if "/email/verify/" in line)
    token = verify_line.rsplit("/", 2)[-2]
    from releasewatch.notifications import user_for_email_verification_token

    assert user_for_email_verification_token(token) == user


def test_account_settings_shows_unverified_status_and_resend_control(client):
    login_unverified_user(client)

    response = client.get(reverse("releasewatch:account_settings"))

    html = response.content.decode()
    assert "Email verification" in html
    assert "not verified" in html.lower()
    assert f'action="{reverse("releasewatch:resend_email_verification")}"' in html
    assert "Resend verification email" in html


def test_account_settings_shows_verified_status_without_resend_control(client):
    user = create_user()
    UserProfile.objects.create(user=user, email_verified_at=timezone.now())
    client.force_login(user)

    response = client.get(reverse("releasewatch:account_settings"))

    html = response.content.decode()
    assert "Email verification" in html
    assert "verified" in html.lower()
    assert f'action="{reverse("releasewatch:resend_email_verification")}"' not in html
    assert "Resend verification email" not in html


def test_email_send_failure_returns_controlled_message_without_token(client, mocker):
    user = login_unverified_user(client)

    def fail_with_message_body(message, *args, **kwargs):
        raise RuntimeError(f"smtp down: {message.body}")

    mocker.patch(
        "django.core.mail.EmailMessage.send",
        autospec=True,
        side_effect=fail_with_message_body,
    )

    response = client.post(reverse("releasewatch:resend_email_verification"), follow=True)

    body = response.content.decode()
    assert response.status_code == 200
    assert "could not send verification email" in body.lower()
    assert "/email/verify/" not in body
    assert "smtp down" not in body
    failure = EmailLog.objects.get(
        user=user,
        message_type=EmailLog.MessageType.VERIFICATION,
        status=EmailLog.Status.FAILED,
    )
    assert failure.error_message == "Verification email delivery failed."
    assert "/email/verify/" not in failure.error_message
    assert "smtp down" not in failure.error_message
