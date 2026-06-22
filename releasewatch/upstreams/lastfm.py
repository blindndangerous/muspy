from copy import deepcopy
from typing import Any

import httpx
from django.conf import settings

from releasewatch.upstreams.base import (
    FixedIntervalThrottle,
    ImportedArtist,
    LockedThrottle,
    UpstreamAuthError,
    UpstreamClient,
    UpstreamError,
    UpstreamRateLimited,
)

_LASTFM_RATE_LIMITED_CODE = 29
_LASTFM_AUTH_ERROR_CODES = {4, 9, 10, 14, 15, 26}


class LastFmClient(UpstreamClient):
    base_url = "https://ws.audioscrobbler.com/2.0/"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        user_agent: str | None = None,
        http_client: httpx.Client | None = None,
        timeout: httpx.Timeout | float | None = None,
        throttle: FixedIntervalThrottle | LockedThrottle | None = None,
    ) -> None:
        self.api_key = settings.LASTFM_API_KEY if api_key is None else api_key
        super().__init__(
            base_url=self.base_url,
            user_agent=user_agent or settings.UPSTREAM_USER_AGENT,
            provider="lastfm",
            http_client=http_client,
            timeout=timeout if timeout is not None else settings.UPSTREAM_HTTP_TIMEOUT_SECONDS,
            throttle=throttle,
        )

    def get_user_top_artists(
        self,
        username: str,
        *,
        period: str = "overall",
        limit: int = 100,
        page: int = 1,
    ) -> list[ImportedArtist]:
        _validate_pagination(limit=limit, page=page)
        payload = self.get_json(
            "/",
            params={
                "method": "user.getTopArtists",
                "user": username,
                "period": period,
                "limit": limit,
                "page": page,
                "api_key": self.api_key,
                "format": "json",
            },
        )
        _raise_for_lastfm_error(payload, provider=self.provider, api_key=self.api_key)
        return [_imported_artist_from_payload(artist) for artist in _artist_rows(payload)]

    def _error_for_response(self, response: httpx.Response) -> UpstreamError:
        payload = _response_payload(response)
        exception_type = _exception_type_for_lastfm_payload(payload)
        if exception_type is None:
            exception_type = self._exception_type_for_status(response.status_code)
            return exception_type(
                f"{self.provider} returned HTTP {response.status_code}",
                provider=self.provider,
                status_code=response.status_code,
                payload=_redact_credentials(payload, api_key=self.api_key),
            )
        return exception_type(
            "lastfm returned an API error",
            provider=self.provider,
            status_code=response.status_code,
            payload=_redact_credentials(payload, api_key=self.api_key),
        )


def _validate_pagination(*, limit: int, page: int) -> None:
    if type(limit) is not int:
        raise ValueError("limit must be an integer")
    if type(page) is not int:
        raise ValueError("page must be an integer")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if page < 1:
        raise ValueError("page must be greater than or equal to 1")


def _raise_for_lastfm_error(payload: Any, *, provider: str, api_key: str) -> None:
    exception_type = _exception_type_for_lastfm_payload(payload)
    if exception_type is None:
        return
    raise exception_type(
        "lastfm returned an API error",
        provider=provider,
        payload=_redact_credentials(payload, api_key=api_key),
    )


def _exception_type_for_lastfm_payload(payload: Any) -> type[UpstreamError] | None:
    if not isinstance(payload, dict):
        return None

    error_code = _lastfm_error_code(payload)
    if error_code == _LASTFM_RATE_LIMITED_CODE:
        return UpstreamRateLimited
    if error_code in _LASTFM_AUTH_ERROR_CODES:
        return UpstreamAuthError
    if error_code is not None:
        return UpstreamError
    return None


def _lastfm_error_code(payload: dict[str, Any]) -> int | None:
    error_code = payload.get("error")
    if type(error_code) is int:
        return error_code
    if isinstance(error_code, str):
        try:
            return int(error_code)
        except ValueError:
            return None
    return None


def _artist_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    topartists = payload.get("topartists", {})
    if not isinstance(topartists, dict):
        return []

    artists = topartists.get("artist", [])
    if isinstance(artists, dict):
        return [artists]
    if isinstance(artists, list):
        return [artist for artist in artists if isinstance(artist, dict)]
    return []


def _imported_artist_from_payload(payload: dict[str, Any]) -> ImportedArtist:
    mbid = _string_field(payload, "mbid")
    return ImportedArtist(
        source_name=_string_field(payload, "name"),
        source_identifier=mbid or _string_field(payload, "url"),
        mbid=mbid,
        raw_payload=deepcopy(payload),
    )


def _response_payload(response: httpx.Response):
    try:
        return response.json()
    except ValueError:
        return {"body": "[invalid json]"}


def _string_field(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    return value if isinstance(value, str) else ""


def _redact_credentials(payload: Any, *, api_key: str) -> Any:
    redacted = payload
    for value in (api_key, settings.LASTFM_API_SECRET):
        if value:
            redacted = _redact_string(redacted, value)
    return redacted


def _redact_string(payload: Any, value: str) -> Any:
    if isinstance(payload, dict):
        return {key: _redact_string(child, value) for key, child in payload.items()}
    if isinstance(payload, list):
        return [_redact_string(item, value) for item in payload]
    if isinstance(payload, str):
        return payload.replace(value, "[redacted]")
    return payload
