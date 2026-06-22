from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class ProviderTokenError(ValueError):
    pass


def encrypt_provider_token(token: str) -> str:
    if not token:
        return ""
    return _fernet().encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_provider_token(token_encrypted: str) -> str:
    if not token_encrypted:
        return ""
    try:
        return _fernet().decrypt(token_encrypted.encode("ascii")).decode("utf-8")
    except InvalidToken as error:
        raise ProviderTokenError("Provider token could not be decrypted.") from error


def redact_provider_secrets(payload: Any, *, secret_values: list[str]) -> Any:
    redacted = payload
    for value in secret_values:
        if value:
            redacted = _redact_string(redacted, value)
    return redacted


def _fernet() -> Fernet:
    key = settings.PROVIDER_TOKEN_ENCRYPTION_KEY
    if not key:
        raise ImproperlyConfigured(
            "PROVIDER_TOKEN_ENCRYPTION_KEY must be set to store provider tokens."
        )
    return Fernet(key.encode("ascii"))


def _redact_string(payload: Any, value: str) -> Any:
    if isinstance(payload, dict):
        return {key: _redact_string(child, value) for key, child in payload.items()}
    if isinstance(payload, list):
        return [_redact_string(item, value) for item in payload]
    if isinstance(payload, str):
        return payload.replace(value, "[redacted]")
    return payload
