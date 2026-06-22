import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from releasewatch.models import ProviderAccount


def create_user(username="provider-user"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="test-pass-123",  # noqa: S106
    )


@pytest.mark.django_db
def test_provider_account_stores_recurring_import_identity_without_token():
    user = create_user()

    account = ProviderAccount.objects.create(
        user=user,
        provider=ProviderAccount.Provider.LASTFM,
        external_username="listener",
    )

    assert account.status == ProviderAccount.Status.ACTIVE
    assert account.token_encrypted == ""
    assert account.scopes == []
    assert str(account) == "lastfm:listener"


@pytest.mark.django_db
def test_provider_account_is_unique_per_user_provider_and_username():
    user = create_user()
    ProviderAccount.objects.create(
        user=user,
        provider=ProviderAccount.Provider.LISTENBRAINZ,
        external_username="listener",
    )

    with pytest.raises(IntegrityError):
        ProviderAccount.objects.create(
            user=user,
            provider=ProviderAccount.Provider.LISTENBRAINZ,
            external_username="listener",
        )


@pytest.mark.django_db
def test_revoked_provider_account_allows_reconnect_with_same_username():
    user = create_user("reconnect-user")
    ProviderAccount.objects.create(
        user=user,
        provider=ProviderAccount.Provider.LISTENBRAINZ,
        external_username="listener",
        status=ProviderAccount.Status.REVOKED,
    )

    active = ProviderAccount.objects.create(
        user=user,
        provider=ProviderAccount.Provider.LISTENBRAINZ,
        external_username="listener",
    )

    assert active.status == ProviderAccount.Status.ACTIVE


def test_provider_account_is_registered_without_token_search():
    import releasewatch.admin  # noqa: F401

    model_admin = admin.site._registry[ProviderAccount]

    assert "token_encrypted" not in model_admin.search_fields
    assert "token_encrypted" not in model_admin.list_display
    assert "token_encrypted" in model_admin.exclude
