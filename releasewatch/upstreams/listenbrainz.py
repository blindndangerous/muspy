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
        _validate_pagination(count=count, offset=offset)
        payload = self.get_json(
            f"/1/stats/user/{quote(username, safe='')}/artists",
            params={"count": count, "offset": offset},
            headers={"Authorization": f"Token {token}"},
        )
        artists = payload.get("payload", {}).get("artists", [])
        return [_imported_artist_from_payload(artist) for artist in artists]

    def _handle_response_metadata(self, response: httpx.Response) -> None:
        self.last_response_metadata = UpstreamResponseMetadata(
            limit=_parse_rate_limit_header(response, "X-RateLimit-Limit"),
            remaining=_parse_rate_limit_header(response, "X-RateLimit-Remaining"),
            reset_in_seconds=_parse_rate_limit_header(response, "X-RateLimit-Reset-In"),
        )

    def _error_for_response(self, response: httpx.Response):
        if response.status_code != 429:
            return super()._error_for_response(response)

        return UpstreamRateLimited(
            "listenbrainz returned HTTP 429",
            provider=self.provider,
            status_code=response.status_code,
            payload=_payload_with_rate_limit(
                _response_payload(response),
                self.last_response_metadata,
            ),
        )


def _validate_pagination(*, count: int, offset: int) -> None:
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
        return int(value)
    except ValueError:
        return None


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
