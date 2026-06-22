from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest

from releasewatch.upstreams import ImportedArtist
from releasewatch.upstreams.base import (
    FixedIntervalThrottle,
    UpstreamAuthError,
    UpstreamRateLimited,
    UpstreamResponseMetadata,
    UpstreamUnavailable,
)
from releasewatch.upstreams.listenbrainz import ListenBrainzClient

USER_AGENT = "muspy-test/1.0 (https://example.invalid/contact)"
ARTIST_MBID = "0b7f80cf-65c3-4d40-99ca-775f7d30c079"


def _instant_throttle():
    return FixedIntervalThrottle(0.0)


def _client_for(handler):
    return ListenBrainzClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        throttle=_instant_throttle(),
    )


def test_listenbrainz_root_url_is_production_api_root():
    client = _client_for(lambda request: httpx.Response(200, json={"payload": {"artists": []}}))

    assert ListenBrainzClient.base_url == "https://api.listenbrainz.org"
    assert client.base_url == "https://api.listenbrainz.org"


def test_get_user_artists_sends_authenticated_request_with_count_and_offset():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["authorization"] = request.headers["authorization"]
        return httpx.Response(200, json={"payload": {"artists": []}})

    client = _client_for(handler)

    assert client.get_user_artists("listener", "secret-token", count=25, offset=50) == []
    assert seen == {
        "path": "/1/stats/user/listener/artists",
        "params": {"count": "25", "offset": "50"},
        "authorization": "Token secret-token",
    }


def test_get_user_artists_url_encodes_username_path_segments():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"payload": {"artists": []}})

    client = _client_for(handler)

    assert client.get_user_artists("listener name/with slash", "secret-token") == []
    assert (
        seen["url"]
        == "https://api.listenbrainz.org/1/stats/user/listener%20name%2Fwith%20slash/artists?count=100&offset=0"
    )


def test_get_user_artists_parses_rate_limit_headers_into_response_metadata():
    def handler(request):
        return httpx.Response(
            200,
            headers={
                "X-RateLimit-Limit": "300",
                "X-RateLimit-Remaining": "299",
                "X-RateLimit-Reset-In": "42",
            },
            json={"payload": {"artists": []}},
        )

    client = _client_for(handler)

    client.get_user_artists("listener", "secret-token")

    assert client.last_response_metadata == UpstreamResponseMetadata(
        limit=300,
        remaining=299,
        reset_in_seconds=42,
    )


def test_get_user_artists_parses_invalid_or_negative_rate_limit_headers_as_none():
    def handler(request):
        return httpx.Response(
            200,
            headers={
                "X-RateLimit-Limit": "-1",
                "X-RateLimit-Remaining": "invalid",
                "X-RateLimit-Reset-In": "-42",
            },
            json={"payload": {"artists": []}},
        )

    client = _client_for(handler)

    client.get_user_artists("listener", "secret-token")

    assert client.last_response_metadata == UpstreamResponseMetadata(
        limit=None,
        remaining=None,
        reset_in_seconds=None,
    )


def test_get_user_artists_returns_empty_list_for_no_content_response():
    def handler(request):
        return httpx.Response(
            204,
            headers={
                "X-RateLimit-Limit": "300",
                "X-RateLimit-Remaining": "299",
                "X-RateLimit-Reset-In": "42",
            },
        )

    client = _client_for(handler)

    assert client.get_user_artists("listener", "secret-token") == []
    assert client.last_response_metadata == UpstreamResponseMetadata(
        limit=300,
        remaining=299,
        reset_in_seconds=42,
    )


def test_get_user_artists_maps_provider_rows_to_imported_artists():
    payload = {
        "payload": {
            "artists": [
                {
                    "artist_mbid": ARTIST_MBID,
                    "artist_name": "Fugazi",
                    "listen_count": 385,
                },
                {
                    "artist_name": "Unmatched Artist",
                    "listen_count": 12,
                    "source_id": "listenbrainz-unmatched-1",
                },
                {
                    "artist_name": "Missing Identifier",
                    "listen_count": 1,
                },
            ]
        }
    }

    client = _client_for(lambda request: httpx.Response(200, json=payload))

    artists = client.get_user_artists("listener", "secret-token")

    assert artists == [
        ImportedArtist(
            source_name="Fugazi",
            source_identifier=ARTIST_MBID,
            mbid=ARTIST_MBID,
            raw_payload=artists[0].raw_payload,
        ),
        ImportedArtist(
            source_name="Unmatched Artist",
            source_identifier="listenbrainz-unmatched-1",
            mbid="",
            raw_payload=artists[1].raw_payload,
        ),
        ImportedArtist(
            source_name="Missing Identifier",
            source_identifier="",
            mbid="",
            raw_payload=artists[2].raw_payload,
        ),
    ]
    assert artists[0].raw_payload["listen_count"] == 385


def test_get_user_artists_maps_401_to_auth_error():
    client = _client_for(lambda request: httpx.Response(401, json={"error": "invalid token"}))

    with pytest.raises(UpstreamAuthError) as exc_info:
        client.get_user_artists("listener", "bad-token")

    assert exc_info.value.status_code == 401
    assert exc_info.value.payload == {"error": "invalid token"}


def test_get_user_artists_maps_429_to_rate_limited_with_reset_seconds():
    def handler(request):
        return httpx.Response(
            429,
            headers={"X-RateLimit-Reset-In": "17"},
            json={"error": "slow down"},
        )

    client = _client_for(handler)

    with pytest.raises(UpstreamRateLimited) as exc_info:
        client.get_user_artists("listener", "secret-token")

    assert exc_info.value.status_code == 429
    assert exc_info.value.payload == {
        "error": "slow down",
        "rate_limit": {"limit": None, "remaining": None, "reset_in_seconds": 17},
    }
    assert client.last_response_metadata.reset_in_seconds == 17


def test_get_user_artists_redacts_token_echoed_in_rate_limit_error_body():
    auth_value = "listenbrainz-redaction-sentinel"

    def handler(request):
        return httpx.Response(
            429,
            json={"error": f"rate limited for Token {auth_value}", "detail": auth_value},
        )

    client = _client_for(handler)

    with pytest.raises(UpstreamRateLimited) as exc_info:
        client.get_user_artists("listener", auth_value)

    assert auth_value not in str(exc_info.value.payload)


def test_get_user_artists_redacts_tokens_during_concurrent_errors():
    barrier = Barrier(2)

    def handler(request):
        token = request.headers["authorization"].removeprefix("Token ")
        barrier.wait(timeout=5)
        return httpx.Response(429, json={"error": f"invalid {token}"})

    client = _client_for(handler)

    def payload_for(token):
        with pytest.raises(UpstreamRateLimited) as exc_info:
            client.get_user_artists("listener", token)
        return exc_info.value.payload

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_payload, second_payload = executor.map(payload_for, ["token-a", "token-b"])

    assert "token-a" not in str(first_payload)
    assert "token-b" not in str(first_payload)
    assert "token-a" not in str(second_payload)
    assert "token-b" not in str(second_payload)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"count": 0},
        {"count": 1001},
        {"offset": -1},
        {"count": True},
        {"count": 1.5},
        {"count": "100"},
        {"offset": False},
        {"offset": 1.5},
        {"offset": "0"},
    ],
)
def test_get_user_artists_rejects_invalid_count_and_offset(kwargs):
    client = _client_for(lambda request: httpx.Response(200, json={"payload": {"artists": []}}))

    with pytest.raises(ValueError):
        client.get_user_artists("listener", "secret-token", **kwargs)


def test_get_user_artists_clears_stale_metadata_before_request_error():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                headers={"X-RateLimit-Reset-In": "17"},
                json={"payload": {"artists": []}},
            )
        raise httpx.ConnectError("network down", request=request)

    client = _client_for(handler)
    client.get_user_artists("listener", "secret-token")
    assert client.last_response_metadata == UpstreamResponseMetadata(
        limit=None,
        remaining=None,
        reset_in_seconds=17,
    )

    with pytest.raises(UpstreamUnavailable):
        client.get_user_artists("listener", "secret-token")

    assert client.last_response_metadata is None


def test_imported_artist_raw_payload_is_deep_copied_before_storage():
    provider_artist = {
        "artist_mbid": ARTIST_MBID,
        "artist_name": "Fugazi",
        "nested": {"tags": ["post-hardcore"]},
    }
    payload = {"payload": {"artists": [provider_artist]}}
    client = _client_for(lambda request: httpx.Response(200, json=payload))

    artist = client.get_user_artists("listener", "secret-token")[0]
    provider_artist["artist_name"] = "Changed"
    provider_artist["nested"]["tags"][0] = "changed nested"

    assert artist.raw_payload["artist_name"] == "Fugazi"
    assert artist.raw_payload["nested"]["tags"] == ["post-hardcore"]
