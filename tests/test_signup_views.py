from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from releasewatch.forms import InviteSignupForm
from releasewatch.models import Invite

pytestmark = pytest.mark.django_db


def test_signup_with_invite_renders_accessible_form(client):
    Invite.objects.create(code="welcome")

    response = client.get(reverse("releasewatch:signup_with_invite", args=["welcome"]))

    assert response.status_code == 200
    html = response.content.decode()
    assert "<h1>Create account</h1>" in html
    assert 'method="post"' in html
    assert 'name="username"' in html
    assert 'name="email"' in html
    assert 'name="password1"' in html
    assert 'name="password2"' in html
    assert 'id="id_username_helptext"' in html
    assert 'aria-describedby="id_username_helptext"' in html


def test_signup_with_invite_creates_user_uses_invite_and_logs_in(client):
    invite = Invite.objects.create(code="welcome")

    response = client.post(
        reverse("releasewatch:signup_with_invite", args=[invite.code]),
        {
            "username": "newlistener",
            "email": "newlistener@example.test",
            "password1": "A-django-safe-passphrase-123",
            "password2": "A-django-safe-passphrase-123",
        },
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("releasewatch:dashboard")
    user = get_user_model().objects.get(username="newlistener")
    assert user.email == "newlistener@example.test"
    invite.refresh_from_db()
    assert invite.uses == 1
    assert str(client.session["_auth_user_id"]) == str(user.pk)


def test_signup_with_used_invite_returns_not_found(client):
    Invite.objects.create(code="used", max_uses=1, uses=1)

    response = client.get(reverse("releasewatch:signup_with_invite", args=["used"]))

    assert response.status_code == 404


def test_signup_with_expired_invite_returns_not_found(client):
    Invite.objects.create(code="expired", expires_at=timezone.now() - timedelta(minutes=1))

    response = client.get(reverse("releasewatch:signup_with_invite", args=["expired"]))

    assert response.status_code == 404


def test_signup_with_duplicate_username_does_not_use_invite(client):
    get_user_model().objects.create_user(username="taken", password="test-password")  # noqa: S106
    invite = Invite.objects.create(code="welcome")

    response = client.post(
        reverse("releasewatch:signup_with_invite", args=[invite.code]),
        {
            "username": "taken",
            "email": "taken@example.test",
            "password1": "A-django-safe-passphrase-123",
            "password2": "A-django-safe-passphrase-123",
        },
    )

    assert response.status_code == 200
    assert b"already exists" in response.content
    invite.refresh_from_db()
    assert invite.uses == 0


def test_signup_form_save_without_commit_sets_email_without_saving():
    form = InviteSignupForm(
        data={
            "username": "draftlistener",
            "email": "draftlistener@example.test",
            "password1": "A-django-safe-passphrase-123",
            "password2": "A-django-safe-passphrase-123",
        }
    )

    assert form.is_valid()
    user = form.save(commit=False)

    assert user.pk is None
    assert user.email == "draftlistener@example.test"


def test_signup_rechecks_invite_before_creating_user(client, monkeypatch):
    invite = Invite.objects.create(code="race", max_uses=1)

    def use_invite_then_validate(self):
        Invite.objects.filter(pk=invite.pk).update(uses=1)
        return True

    monkeypatch.setattr("releasewatch.views.InviteSignupForm.is_valid", use_invite_then_validate)

    response = client.post(
        reverse("releasewatch:signup_with_invite", args=[invite.code]),
        {
            "username": "racedlistener",
            "email": "racedlistener@example.test",
            "password1": "A-django-safe-passphrase-123",
            "password2": "A-django-safe-passphrase-123",
        },
    )

    assert response.status_code == 404
    assert not get_user_model().objects.filter(username="racedlistener").exists()
