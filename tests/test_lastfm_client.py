import httpx
import pytest
from django.test import override_settings

from releasewatch.upstreams import ImportedArtist
from releasewatch.upstreams.base import (
    FixedIntervalThrottle,
    UpstreamAuthError,
    UpstreamError,
    UpstreamRateLimited,
    UpstreamUnavailable,
)
from releasewatch.upstreams.lastfm import LastFmClient

USER_AGENT = "muspy-test/1.0 (https://example.invalid/contact)"
API_KEY = "lastfm-api-key"
PRIVATE_VALUE = "lastfm-private-value-sentinel"
ARTIST_MBID = "0b7f80cf-65c3-4d40-99ca-775f7d30c079"


def _instant_throttle():
    return FixedIntervalThrottle(0.0)


def _client_for(handler, *, api_key=API_KEY):
    return LastFmClient(
        api_key=api_key,
        user_agent=USER_AGENT,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        throttle=_instant_throttle(),
    )


def test_lastfm_client_is_exported_from_upstreams_package():
    from releasewatch.upstreams import LastFmClient as ExportedLastFmClient

    assert ExportedLastFmClient is LastFmClient


@override_settings(LASTFM_API_SECRET=PRIVATE_VALUE)
def test_get_user_top_artists_sends_unsigned_import_request_params():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"topartists": {"artist": []}})

    client = _client_for(handler)

    assert (
        client.get_user_top_artists(
            "listener",
            period="7day",
            limit=25,
            page=3,
        )
        == []
    )
    assert seen == {
        "path": "/2.0/",
        "params": {
            "method": "user.getTopArtists",
            "user": "listener",
            "period": "7day",
            "limit": "25",
            "page": "3",
            "api_key": API_KEY,
            "format": "json",
        },
    }
    assert PRIVATE_VALUE not in seen["params"].values()
    assert "api_sig" not in seen["params"]


@override_settings(LASTFM_API_KEY=API_KEY)
def test_get_user_top_artists_uses_settings_api_key_by_default():
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"topartists": {"artist": []}})

    client = LastFmClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        throttle=_instant_throttle(),
    )

    client.get_user_top_artists("listener")

    assert seen["params"]["api_key"] == API_KEY


def test_get_user_top_artists_maps_rows_to_imported_artists():
    payload = {
        "topartists": {
            "artist": [
                {
                    "name": "Fugazi",
                    "mbid": ARTIST_MBID,
                    "url": "https://www.last.fm/music/Fugazi",
                    "playcount": "385",
                },
                {
                    "name": "Unmatched Artist",
                    "mbid": "",
                    "url": "https://www.last.fm/music/Unmatched+Artist",
                },
                {
                    "name": "Missing Identifier",
                    "playcount": "1",
                },
            ]
        }
    }
    client = _client_for(lambda request: httpx.Response(200, json=payload))

    artists = client.get_user_top_artists("listener")

    assert artists == [
        ImportedArtist(
            source_name="Fugazi",
            source_identifier=ARTIST_MBID,
            mbid=ARTIST_MBID,
            raw_payload=artists[0].raw_payload,
        ),
        ImportedArtist(
            source_name="Unmatched Artist",
            source_identifier="https://www.last.fm/music/Unmatched+Artist",
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
    assert artists[0].raw_payload["playcount"] == "385"


def test_get_user_top_artists_accepts_single_artist_object_payload():
    payload = {
        "topartists": {
            "artist": {
                "name": "Fugazi",
                "mbid": ARTIST_MBID,
            }
        }
    }
    client = _client_for(lambda request: httpx.Response(200, json=payload))

    assert client.get_user_top_artists("listener")[0].source_name == "Fugazi"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"topartists": None},
        {"topartists": {"artist": "not-a-row"}},
        {"topartists": {"artist": ["not-a-row"]}},
        {"error": "not-a-number", "topartists": {"artist": []}},
    ],
)
def test_get_user_top_artists_ignores_unusable_artist_payload_shapes(payload):
    client = _client_for(lambda request: httpx.Response(200, json=payload))

    assert client.get_user_top_artists("listener") == []


def test_lastfm_error_29_maps_to_rate_limited():
    client = _client_for(
        lambda request: httpx.Response(
            200,
            json={"error": 29, "message": "Rate limit exceeded"},
        )
    )

    with pytest.raises(UpstreamRateLimited) as exc_info:
        client.get_user_top_artists("listener")

    assert exc_info.value.payload == {"error": 29, "message": "Rate limit exceeded"}


def test_lastfm_http_error_29_maps_to_rate_limited():
    client = _client_for(
        lambda request: httpx.Response(
            429,
            json={"error": 29, "message": "Rate limit exceeded"},
        )
    )

    with pytest.raises(UpstreamRateLimited) as exc_info:
        client.get_user_top_artists("listener")

    assert exc_info.value.status_code == 429
    assert exc_info.value.payload == {"error": 29, "message": "Rate limit exceeded"}


@pytest.mark.parametrize("error_code", [4, 9, 10, 14, 15, 26])
def test_lastfm_auth_and_key_errors_map_to_auth_error(error_code):
    client = _client_for(
        lambda request: httpx.Response(
            200,
            json={"error": error_code, "message": "auth or key error"},
        )
    )

    with pytest.raises(UpstreamAuthError) as exc_info:
        client.get_user_top_artists("listener")

    assert exc_info.value.payload == {
        "error": error_code,
        "message": "auth or key error",
    }


def test_lastfm_string_auth_error_code_maps_to_auth_error():
    client = _client_for(
        lambda request: httpx.Response(
            200,
            json={"error": "10", "message": "Invalid API key"},
        )
    )

    with pytest.raises(UpstreamAuthError):
        client.get_user_top_artists("listener")


def test_lastfm_unknown_error_code_maps_to_upstream_error():
    client = _client_for(
        lambda request: httpx.Response(
            200,
            json={"error": 30, "message": "unknown Last.fm error"},
        )
    )

    with pytest.raises(UpstreamError) as exc_info:
        client.get_user_top_artists("listener")

    assert exc_info.value.payload == {"error": 30, "message": "unknown Last.fm error"}


@override_settings(LASTFM_API_SECRET=PRIVATE_VALUE)
def test_api_secret_is_not_sent_or_kept_in_exception_payload():
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "error": 10,
                "message": f"Invalid API key; secret was {PRIVATE_VALUE}",
                "params": dict(request.url.params),
            },
        )

    client = _client_for(handler)

    with pytest.raises(UpstreamAuthError) as exc_info:
        client.get_user_top_artists("listener")

    assert PRIVATE_VALUE not in seen["params"].values()
    assert "api_sig" not in seen["params"]
    assert PRIVATE_VALUE not in str(exc_info.value.payload)


@override_settings(LASTFM_API_SECRET=PRIVATE_VALUE)
def test_api_secret_is_redacted_from_nested_exception_payload_lists():
    client = _client_for(
        lambda request: httpx.Response(
            200,
            json={
                "error": 30,
                "messages": [f"secret value {PRIVATE_VALUE}"],
            },
        )
    )

    with pytest.raises(UpstreamError) as exc_info:
        client.get_user_top_artists("listener")

    assert PRIVATE_VALUE not in str(exc_info.value.payload)


@override_settings(LASTFM_API_SECRET=PRIVATE_VALUE)
def test_api_secret_is_redacted_from_http_error_payload_without_lastfm_code():
    client = _client_for(
        lambda request: httpx.Response(
            500,
            json={"message": f"upstream included {PRIVATE_VALUE}"},
        )
    )

    with pytest.raises(UpstreamUnavailable) as exc_info:
        client.get_user_top_artists("listener")

    assert PRIVATE_VALUE not in str(exc_info.value.payload)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 1001},
        {"page": 0},
        {"limit": True},
        {"limit": 1.5},
        {"limit": "100"},
        {"page": False},
        {"page": 1.5},
        {"page": "1"},
    ],
)
def test_get_user_top_artists_rejects_invalid_limit_and_page(kwargs):
    client = _client_for(lambda request: httpx.Response(200, json={"topartists": {"artist": []}}))

    with pytest.raises(ValueError):
        client.get_user_top_artists("listener", **kwargs)


def test_imported_artist_raw_payload_is_deep_copied_before_storage():
    provider_artist = {
        "name": "Fugazi",
        "mbid": ARTIST_MBID,
        "nested": {"tags": ["post-hardcore"]},
    }
    payload = {"topartists": {"artist": [provider_artist]}}
    client = _client_for(lambda request: httpx.Response(200, json=payload))

    artist = client.get_user_top_artists("listener")[0]
    provider_artist["name"] = "Changed"
    provider_artist["nested"]["tags"][0] = "changed nested"

    assert artist.raw_payload["name"] == "Fugazi"
    assert artist.raw_payload["nested"]["tags"] == ["post-hardcore"]


def test_invalid_json_maps_to_upstream_unavailable_through_base_client():
    client = _client_for(lambda request: httpx.Response(200, content=b"not-json"))

    with pytest.raises(UpstreamUnavailable):
        client.get_user_top_artists("listener")


def test_invalid_json_http_error_maps_to_upstream_unavailable_through_base_client():
    client = _client_for(lambda request: httpx.Response(500, content=b"not-json"))

    with pytest.raises(UpstreamUnavailable):
        client.get_user_top_artists("listener")
