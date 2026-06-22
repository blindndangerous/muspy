import pytest
from cryptography.fernet import Fernet
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError
from django.test import override_settings

from releasewatch.models import ProviderAccount
from releasewatch.provider_tokens import (
    ProviderTokenError,
    decrypt_provider_token,
    encrypt_provider_token,
    redact_provider_secrets,
)


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


@override_settings(PROVIDER_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode())
def test_provider_token_round_trips_without_plaintext_storage():
    encrypted = encrypt_provider_token("listenbrainz-token")

    assert encrypted != "listenbrainz-token"
    assert "listenbrainz-token" not in encrypted
    assert decrypt_provider_token(encrypted) == "listenbrainz-token"


@override_settings(PROVIDER_TOKEN_ENCRYPTION_KEY="")
def test_encrypt_provider_token_requires_key():
    with pytest.raises(ImproperlyConfigured):
        encrypt_provider_token("listenbrainz-token")


@override_settings(PROVIDER_TOKEN_ENCRYPTION_KEY="not-a-fernet-key")  # noqa: S106
def test_encrypt_provider_token_rejects_invalid_key_as_configuration_error():
    with pytest.raises(ImproperlyConfigured, match="PROVIDER_TOKEN_ENCRYPTION_KEY"):
        encrypt_provider_token("listenbrainz-token")


@override_settings(PROVIDER_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode())
def test_decrypt_provider_token_rejects_malformed_ciphertext_as_token_error():
    with pytest.raises(ProviderTokenError):
        decrypt_provider_token("not \u2603 ascii")


def test_redact_provider_secrets_removes_nested_values():
    payload = {
        "token": "listenbrainz-token",
        "nested": ["api-key", {"secret-lastfm-secret": "lastfm-secret"}],
    }

    redacted = redact_provider_secrets(
        payload,
        secret_values=["listenbrainz-token", "api-key", "lastfm-secret"],
    )

    assert "listenbrainz-token" not in str(redacted)
    assert "api-key" not in str(redacted)
    assert "lastfm-secret" not in str(redacted)
