from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from releasewatch.models import (
    Artist,
    EmailLog,
    FeedToken,
    Follow,
    ImportCandidate,
    ImportRun,
    Notification,
    NotificationPreference,
    ProviderAccount,
    Release,
    ReleaseEvent,
    ReleaseGroup,
    UserProfile,
)

pytestmark = pytest.mark.django_db
TEST_PASSWORD = "test-password"  # noqa: S105


def create_user(username="listener"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password=TEST_PASSWORD,
    )


def create_release_data():
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi", sort_name="Fugazi")
    group = ReleaseGroup.objects.create(mbid=uuid4(), artist=artist, title="Repeater")
    release = Release.objects.create(mbid=uuid4(), release_group=group, country="US")
    event = ReleaseEvent.objects.create(release_group=group, release=release, country="US")
    return artist, group, release, event


def create_owned_data(user):
    artist, _group, _release, event = create_release_data()
    import_run = ImportRun.objects.create(user=user, source=ImportRun.Source.PLAIN_TEXT)

    UserProfile.objects.create(user=user)
    NotificationPreference.objects.create(user=user)
    FeedToken.objects.create(user=user, feed_type=FeedToken.FeedType.RSS, token_hash="a" * 64)
    ProviderAccount.objects.create(
        user=user,
        provider=ProviderAccount.Provider.LASTFM,
        external_username="listener",
    )
    Follow.objects.create(user=user, artist=artist)
    ImportCandidate.objects.create(import_run=import_run, artist=artist, source_name="Fugazi")
    Notification.objects.create(
        user=user,
        release_event=event,
        cadence_bucket="daily:2026-07-06",
    )
    EmailLog.objects.create(user=user, message_type=EmailLog.MessageType.DIGEST)


def test_account_delete_requires_login(client):
    response = client.get(reverse("releasewatch:account_delete"))

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_account_delete_get_renders_accessible_warning_and_settings_link(client):
    user = create_user()
    client.force_login(user)

    response = client.get(reverse("releasewatch:account_delete"))
    settings_response = client.get(reverse("releasewatch:account_settings"))

    assert response.status_code == 200
    html = response.content.decode()
    assert "<h1>Delete account</h1>" in html
    assert "This permanently deletes your account" in html
    assert 'for="id_confirm_delete"' in html
    assert 'name="confirm_delete"' in html
    assert 'href="/settings/account/delete/"' in settings_response.content.decode()


def test_account_delete_invalid_confirmation_rerenders_with_alert(client):
    user = create_user()
    client.force_login(user)

    response = client.post(reverse("releasewatch:account_delete"), {"confirm_delete": "wrong"})

    assert response.status_code == 200
    html = response.content.decode()
    assert 'role="alert"' in html
    assert "Type DELETE to confirm." in html
    assert get_user_model().objects.filter(pk=user.pk).exists()
    assert str(client.session["_auth_user_id"]) == str(user.pk)


def test_account_delete_deletes_user_and_logs_out(client):
    user = create_user()
    client.force_login(user)

    response = client.post(reverse("releasewatch:account_delete"), {"confirm_delete": "DELETE"})

    assert response.status_code == 302
    assert not get_user_model().objects.filter(pk=user.pk).exists()
    assert "_auth_user_id" not in client.session


def test_account_delete_cascades_user_owned_data(client):
    user = create_user()
    create_owned_data(user)
    client.force_login(user)

    response = client.post(reverse("releasewatch:account_delete"), {"confirm_delete": "DELETE"})

    assert response.status_code == 302
    assert UserProfile.objects.count() == 0
    assert NotificationPreference.objects.count() == 0
    assert FeedToken.objects.count() == 0
    assert ProviderAccount.objects.count() == 0
    assert Follow.objects.count() == 0
    assert ImportRun.objects.count() == 0
    assert ImportCandidate.objects.count() == 0
    assert Notification.objects.count() == 0
    assert EmailLog.objects.count() == 0


def test_account_delete_preserves_shared_release_data(client):
    user = create_user()
    create_owned_data(user)
    client.force_login(user)

    response = client.post(reverse("releasewatch:account_delete"), {"confirm_delete": "DELETE"})

    assert response.status_code == 302
    assert Artist.objects.count() == 1
    assert ReleaseGroup.objects.count() == 1
    assert Release.objects.count() == 1
    assert ReleaseEvent.objects.count() == 1


def test_account_delete_requires_csrf_token():
    user = create_user("csrf-user")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    response = client.post(reverse("releasewatch:account_delete"), {"confirm_delete": "DELETE"})

    assert response.status_code == 403
