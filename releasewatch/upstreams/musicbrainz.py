from copy import deepcopy
from typing import Any

import httpx
from django.conf import settings

from releasewatch.upstreams.base import (
    FixedIntervalThrottle,
    LockedThrottle,
    UpstreamArtist,
    UpstreamArtistAlias,
    UpstreamClient,
    UpstreamRelease,
    UpstreamReleaseGroup,
    parse_partial_date,
)

_DEFAULT_THROTTLE = LockedThrottle(FixedIntervalThrottle(1.0))


class MusicBrainzClient(UpstreamClient):
    base_url = "https://musicbrainz.org/ws/2"

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        http_client: httpx.Client | None = None,
        timeout: httpx.Timeout | float | None = None,
        throttle: FixedIntervalThrottle | LockedThrottle | None = None,
    ) -> None:
        super().__init__(
            base_url=self.base_url,
            user_agent=user_agent or settings.UPSTREAM_USER_AGENT,
            provider="musicbrainz",
            http_client=http_client,
            timeout=timeout if timeout is not None else settings.UPSTREAM_HTTP_TIMEOUT_SECONDS,
            throttle=throttle if throttle is not None else _DEFAULT_THROTTLE,
            rate_limit_status_codes={429, 503},
        )

    def lookup_artist(self, mbid: str) -> UpstreamArtist:
        payload = self.get_json(
            f"/artist/{mbid}",
            params={"fmt": "json", "inc": "aliases+url-rels"},
        )
        return _artist_from_payload(payload)

    def search_artists(
        self,
        query: str,
        *,
        limit: int = 10,
        offset: int = 0,
    ) -> list[UpstreamArtist]:
        _validate_pagination(limit=limit, offset=offset)
        payload = self.get_json(
            "/artist",
            params={
                "query": query,
                "limit": limit,
                "offset": offset,
                "fmt": "json",
            },
        )
        return [_artist_from_payload(artist) for artist in payload.get("artists", [])]

    def browse_release_groups(
        self,
        artist_mbid: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UpstreamReleaseGroup]:
        _validate_pagination(limit=limit, offset=offset)
        payload = self.get_json(
            "/release-group",
            params={
                "artist": artist_mbid,
                "limit": limit,
                "offset": offset,
                "fmt": "json",
            },
        )
        return [
            _release_group_from_payload(release_group)
            for release_group in payload.get("release-groups", [])
        ]

    def lookup_release_group(self, mbid: str) -> UpstreamReleaseGroup:
        payload = self.get_json(
            f"/release-group/{mbid}",
            params={"fmt": "json"},
        )
        return _release_group_from_payload(payload)

    def browse_releases_by_release_group(
        self,
        release_group_mbid: str,
        *,
        status: str = "official",
        limit: int = 100,
        offset: int = 0,
    ) -> list[UpstreamRelease]:
        _validate_pagination(limit=limit, offset=offset)
        payload = self.get_json(
            "/release",
            params={
                "release-group": release_group_mbid,
                "status": status,
                "limit": limit,
                "offset": offset,
                "inc": "media+release-groups",
                "fmt": "json",
            },
        )
        return [_release_from_payload(release) for release in payload.get("releases", [])]


def _validate_pagination(*, limit: int, offset: int) -> None:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0")


def _artist_from_payload(payload: dict[str, Any]) -> UpstreamArtist:
    return UpstreamArtist(
        mbid=payload.get("id", ""),
        name=payload.get("name", ""),
        sort_name=payload.get("sort-name", ""),
        disambiguation=payload.get("disambiguation", ""),
        artist_type=payload.get("type", ""),
        country=payload.get("country", ""),
        aliases=[_alias_from_payload(alias) for alias in payload.get("aliases", [])],
        raw_payload=deepcopy(payload),
    )


def _alias_from_payload(payload: dict[str, Any]) -> UpstreamArtistAlias:
    return UpstreamArtistAlias(
        name=payload.get("name", ""),
        sort_name=payload.get("sort-name", ""),
        locale=payload.get("locale", ""),
        alias_type=payload.get("type", ""),
        primary=bool(payload.get("primary", False)),
    )


def _release_group_from_payload(payload: dict[str, Any]) -> UpstreamReleaseGroup:
    first_release_date, first_release_precision = parse_partial_date(
        payload.get("first-release-date", "")
    )
    return UpstreamReleaseGroup(
        mbid=payload.get("id", ""),
        title=payload.get("title", ""),
        primary_type=payload.get("primary-type", ""),
        secondary_types=list(payload.get("secondary-types", [])),
        first_release_date=first_release_date,
        first_release_precision=first_release_precision,
        raw_payload=deepcopy(payload),
    )


def _release_from_payload(payload: dict[str, Any]) -> UpstreamRelease:
    release_date, release_date_precision = parse_partial_date(payload.get("date", ""))
    return UpstreamRelease(
        mbid=payload.get("id", ""),
        country=payload.get("country", ""),
        release_date=release_date,
        release_date_precision=release_date_precision,
        status=payload.get("status", ""),
        media_format=_media_format_from_payload(payload),
        raw_payload=deepcopy(payload),
    )


def _media_format_from_payload(payload: dict[str, Any]) -> str:
    for medium in payload.get("media", []):
        media_format = medium.get("format", "")
        if media_format:
            return media_format
    return ""
