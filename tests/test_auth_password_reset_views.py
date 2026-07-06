import re

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

pytestmark = pytest.mark.django_db


def create_user(username="listener"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="old-test-password",  # noqa: S106
    )


def reset_confirm_url(user, token=None):
    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    return reverse(
        "password_reset_confirm",
        args=[uidb64, token or default_token_generator.make_token(user)],
    )


def test_login_page_links_to_password_reset(client):
    response = client.get(reverse("login"))

    assert response.status_code == 200
    html = response.content.decode()
    assert reverse("password_reset") in html
    assert "Forgot your password?" in html


def test_password_reset_form_renders_accessible_branded_template(client):
    response = client.get(reverse("password_reset"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "<h1>Reset your Muspy password</h1>" in html
    assert "<main" in html
    assert 'method="post"' in html
    assert 'name="email"' in html
    assert 'for="id_email"' in html


def test_password_reset_done_renders_accessible_branded_template(client):
    response = client.get(reverse("password_reset_done"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "<h1>Check your email</h1>" in html
    assert "Muspy password reset link" in html
    assert "<main" in html


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_password_reset_sends_branded_email_with_reset_link(client):
    user = create_user()

    response = client.post(
        reverse("password_reset"),
        {"email": user.email},
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("password_reset_done")
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == [user.email]
    assert message.subject == "Reset your Muspy password"
    assert "requested for your Muspy account" in message.body
    assert re.search(r"/accounts/reset/[-\w]+/[-\w]+/", message.body)


def test_password_reset_confirm_accepts_valid_token_and_completes_reset(client):
    user = create_user()

    response = client.get(reset_confirm_url(user), follow=True)

    assert response.status_code == 200
    html = response.content.decode()
    assert "<h1>Choose a new password</h1>" in html
    assert 'name="new_password1"' in html
    assert 'name="new_password2"' in html

    post_path = response.request["PATH_INFO"]
    response = client.post(
        post_path,
        {
            "new_password1": "A-django-safe-passphrase-456",
            "new_password2": "A-django-safe-passphrase-456",
        },
        follow=True,
    )

    assert response.status_code == 200
    html = response.content.decode()
    assert "<h1>Password reset complete</h1>" in html
    assert reverse("login") in html
    user.refresh_from_db()
    assert user.check_password("A-django-safe-passphrase-456")


def test_password_reset_confirm_rejects_invalid_token(client):
    user = create_user()

    response = client.get(reset_confirm_url(user, "not-a-valid-token"), follow=True)

    assert response.status_code == 200
    html = response.content.decode()
    assert "<h1>Password reset link invalid</h1>" in html
    assert 'name="new_password1"' not in html
