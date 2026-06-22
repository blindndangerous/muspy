from contextvars import ContextVar
from copy import deepcopy
from dataclasses import asdict
from typing import Any
from urllib.parse import quote

import httpx
from django.conf import settings

from releasewatch.upstreams.base import (
    FixedIntervalThrottle,
    ImportedArtist,
    LockedThrottle,
    UpstreamClient,
    UpstreamRateLimited,
    UpstreamResponseMetadata,
    UpstreamUnavailable,
)

_ACTIVE_AUTH_TOKEN: ContextVar[str | None] = ContextVar("listenbrainz_auth_token", default=None)
_ACTIVE_RESPONSE_METADATA: ContextVar[UpstreamResponseMetadata | None] = ContextVar(
    "listenbrainz_response_metadata",
    default=None,
)


class ListenBrainzClient(UpstreamClient):
    base_url = "https://api.listenbrainz.org"

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        http_client: httpx.Client | None = None,
        timeout: httpx.Timeout | float | None = None,
        throttle: FixedIntervalThrottle | LockedThrottle | None = None,
    ) -> None:
        self.last_response_metadata: UpstreamResponseMetadata | None = None
        super().__init__(
            base_url=self.base_url,
            user_agent=user_agent or settings.UPSTREAM_USER_AGENT,
            provider="listenbrainz",
            http_client=http_client,
            timeout=timeout if timeout is not None else settings.UPSTREAM_HTTP_TIMEOUT_SECONDS,
            throttle=throttle,
        )

    def get_user_artists(
        self,
        username: str,
        token: str,
        *,
        count: int = 100,
        offset: int = 0,
    ) -> list[ImportedArtist]:
        self.last_response_metadata = None
        active_response_metadata = _ACTIVE_RESPONSE_METADATA.set(None)
        _validate_pagination(count=count, offset=offset)
        active_auth_token = _ACTIVE_AUTH_TOKEN.set(token)
        try:
            payload = self.get_json(
                f"/1/stats/user/{quote(username, safe='')}/artists",
                params={"count": count, "offset": offset},
                headers={"Authorization": f"Token {token}"},
            )
        except UpstreamUnavailable as exc:
            if exc.status_code == 204:
                return []
            raise
        finally:
            _ACTIVE_AUTH_TOKEN.reset(active_auth_token)
            _ACTIVE_RESPONSE_METADATA.reset(active_response_metadata)
        artists = payload.get("payload", {}).get("artists", [])
        return [_imported_artist_from_payload(artist) for artist in artists]

    def _handle_response_metadata(self, response: httpx.Response) -> None:
        metadata = UpstreamResponseMetadata(
            limit=_parse_rate_limit_header(response, "X-RateLimit-Limit"),
            remaining=_parse_rate_limit_header(response, "X-RateLimit-Remaining"),
            reset_in_seconds=_parse_rate_limit_header(response, "X-RateLimit-Reset-In"),
        )
        _ACTIVE_RESPONSE_METADATA.set(metadata)
        self.last_response_metadata = metadata

    def _error_for_response(self, response: httpx.Response):
        payload = _response_payload(response)
        active_auth_token = _ACTIVE_AUTH_TOKEN.get()
        if active_auth_token:
            payload = _redact_auth_token(payload, active_auth_token)

        if response.status_code != 429:
            exception_type = self._exception_type_for_status(response.status_code)
            return exception_type(
                f"{self.provider} returned HTTP {response.status_code}",
                provider=self.provider,
                status_code=response.status_code,
                payload=payload,
            )

        return UpstreamRateLimited(
            "listenbrainz returned HTTP 429",
            provider=self.provider,
            status_code=response.status_code,
            payload=_payload_with_rate_limit(
                payload,
                _ACTIVE_RESPONSE_METADATA.get(),
            ),
        )


def _validate_pagination(*, count: int, offset: int) -> None:
    if type(count) is not int:
        raise ValueError("count must be an integer")
    if type(offset) is not int:
        raise ValueError("offset must be an integer")
    if not 1 <= count <= 1000:
        raise ValueError("count must be between 1 and 1000")
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0")


def _imported_artist_from_payload(payload: dict[str, Any]) -> ImportedArtist:
    mbid = payload.get("artist_mbid", "")
    return ImportedArtist(
        source_name=payload.get("artist_name", ""),
        source_identifier=mbid or _fallback_source_identifier(payload),
        mbid=mbid,
        raw_payload=deepcopy(payload),
    )


def _fallback_source_identifier(payload: dict[str, Any]) -> str:
    for key in ("source_id", "artist_id", "id"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _parse_rate_limit_header(response: httpx.Response, header_name: str) -> int | None:
    value = response.headers.get(header_name)
    if value is None:
        return None
    try:
        parsed_value = int(value)
    except ValueError:
        return None
    if parsed_value < 0:
        return None
    return parsed_value


def _payload_with_rate_limit(
    payload: Any,
    metadata: UpstreamResponseMetadata | None,
) -> dict[str, Any]:
    if isinstance(payload, dict):
        rate_limited_payload = dict(payload)
    else:
        rate_limited_payload = {"payload": payload}
    rate_limited_payload["rate_limit"] = (
        asdict(metadata)
        if metadata is not None
        else {"limit": None, "remaining": None, "reset_in_seconds": None}
    )
    return rate_limited_payload


def _response_payload(response: httpx.Response):
    try:
        return response.json()
    except ValueError:
        return {"body": "[invalid json]"}


def _redact_auth_token(payload: Any, token: str) -> Any:
    if isinstance(payload, dict):
        return {key: _redact_auth_token(value, token) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_redact_auth_token(item, token) for item in payload]
    if isinstance(payload, str):
        return payload.replace(token, "[redacted]")
    return payload
