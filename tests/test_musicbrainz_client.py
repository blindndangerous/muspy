from datetime import date

import httpx
import pytest

from releasewatch.models import DatePrecision
from releasewatch.upstreams import (
    UpstreamArtist,
    UpstreamArtistAlias,
    UpstreamRateLimited,
    UpstreamReleaseGroup,
)
from releasewatch.upstreams.base import FixedIntervalThrottle, LockedThrottle
from releasewatch.upstreams.musicbrainz import (
    MusicBrainzClient,
    _artist_from_payload,
    _release_group_from_payload,
)

USER_AGENT = "muspy-test/1.0 (https://example.invalid/contact)"
ARTIST_MBID = "0b7f80cf-65c3-4d40-99ca-775f7d30c079"
RELEASE_GROUP_MBID = "9f16e52e-0d5b-4caa-999c-a6c5f3c2b75f"


def _instant_throttle():
    return FixedIntervalThrottle(0.0)


def test_lookup_artist_requests_artist_endpoint_with_json_and_user_agent():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["user_agent"] = request.headers["user-agent"]
        return httpx.Response(
            200,
            json={
                "id": ARTIST_MBID,
                "name": "Fugazi",
                "sort-name": "Fugazi",
                "type": "Group",
                "country": "US",
                "disambiguation": "Washington, D.C. post-hardcore band",
                "aliases": [],
            },
        )

    client = MusicBrainzClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        throttle=_instant_throttle(),
    )

    artist = client.lookup_artist(ARTIST_MBID)

    assert seen == {
        "path": f"/ws/2/artist/{ARTIST_MBID}",
        "params": {"fmt": "json", "inc": "aliases"},
        "user_agent": USER_AGENT,
    }
    assert artist == UpstreamArtist(
        mbid=ARTIST_MBID,
        name="Fugazi",
        sort_name="Fugazi",
        disambiguation="Washington, D.C. post-hardcore band",
        artist_type="Group",
        country="US",
        aliases=[],
        raw_payload=artist.raw_payload,
    )


def test_lookup_artist_maps_aliases_and_keeps_unmodeled_fields_in_raw_payload():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "id": ARTIST_MBID,
                "name": "Nina Simone",
                "sort-name": "Simone, Nina",
                "type": "Person",
                "country": "US",
                "disambiguation": "",
                "life-span": {"ended": True},
                "unrelated": {"kept": True},
                "aliases": [
                    {
                        "name": "Eunice Waymon",
                        "sort-name": "Waymon, Eunice",
                        "locale": "en",
                        "type": "Legal name",
                        "primary": False,
                    }
                ],
            },
        )

    client = MusicBrainzClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        throttle=_instant_throttle(),
    )

    artist = client.lookup_artist(ARTIST_MBID)

    assert artist.aliases == [
        UpstreamArtistAlias(
            name="Eunice Waymon",
            sort_name="Waymon, Eunice",
            locale="en",
            alias_type="Legal name",
            primary=False,
        )
    ]
    assert not hasattr(artist, "life_span")
    assert not hasattr(artist, "ended")
    assert artist.raw_payload["life-span"]["ended"] is True
    assert artist.raw_payload["unrelated"] == {"kept": True}


def test_browse_release_groups_maps_first_release_date_and_precision():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "release-groups": [
                    {
                        "id": RELEASE_GROUP_MBID,
                        "title": "Repeater",
                        "primary-type": "Album",
                        "secondary-types": ["Compilation"],
                        "first-release-date": "1990-04",
                        "artist-credit": [{"name": "Fugazi"}],
                    }
                ]
            },
        )

    client = MusicBrainzClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        throttle=_instant_throttle(),
    )

    release_groups = client.browse_release_groups(ARTIST_MBID, limit=25, offset=50)

    assert seen == {
        "path": "/ws/2/release-group",
        "params": {
            "artist": ARTIST_MBID,
            "limit": "25",
            "offset": "50",
            "fmt": "json",
        },
    }
    assert release_groups == [
        UpstreamReleaseGroup(
            mbid=RELEASE_GROUP_MBID,
            title="Repeater",
            primary_type="Album",
            secondary_types=["Compilation"],
            first_release_date=date(1990, 4, 1),
            first_release_precision=DatePrecision.MONTH,
            raw_payload=release_groups[0].raw_payload,
        )
    ]
    assert release_groups[0].raw_payload["artist-credit"] == [{"name": "Fugazi"}]


def test_lookup_release_group_maps_release_group_payload():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "id": RELEASE_GROUP_MBID,
                "title": "In on the Kill Taker",
                "primary-type": "Album",
                "secondary-types": [],
                "first-release-date": "1993-06-30",
            },
        )

    client = MusicBrainzClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        throttle=_instant_throttle(),
    )

    release_group = client.lookup_release_group(RELEASE_GROUP_MBID)

    assert release_group.mbid == RELEASE_GROUP_MBID
    assert release_group.title == "In on the Kill Taker"
    assert release_group.first_release_date == date(1993, 6, 30)
    assert release_group.first_release_precision == DatePrecision.DAY


def test_musicbrainz_maps_503_to_rate_limited():
    def handler(request):
        return httpx.Response(503, json={"error": "rate limited"})

    client = MusicBrainzClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        throttle=_instant_throttle(),
    )

    with pytest.raises(UpstreamRateLimited) as exc_info:
        client.lookup_artist(ARTIST_MBID)

    assert exc_info.value.status_code == 503


def test_musicbrainz_default_throttle_waits_between_calls(monkeypatch):
    current = {"value": 10.0}
    sleeps = []
    monkeypatch.setattr(
        "releasewatch.upstreams.musicbrainz._DEFAULT_THROTTLE",
        LockedThrottle(FixedIntervalThrottle(1.0)),
    )
    monkeypatch.setattr("releasewatch.upstreams.base.time.monotonic", lambda: current["value"])

    def fake_sleep(seconds):
        sleeps.append(seconds)
        current["value"] += seconds

    monkeypatch.setattr("releasewatch.upstreams.base.time.sleep", fake_sleep)

    def handler(request):
        return httpx.Response(
            200,
            json={
                "id": ARTIST_MBID,
                "name": "Fugazi",
                "sort-name": "Fugazi",
                "aliases": [],
            },
        )

    client = MusicBrainzClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.lookup_artist(ARTIST_MBID)
    client.lookup_artist(ARTIST_MBID)

    assert sleeps == [1.0]


def test_musicbrainz_default_throttle_is_shared_across_client_instances(monkeypatch):
    current = {"value": 10.0}
    sleeps = []
    monkeypatch.setattr(
        "releasewatch.upstreams.musicbrainz._DEFAULT_THROTTLE",
        LockedThrottle(FixedIntervalThrottle(1.0)),
    )
    monkeypatch.setattr("releasewatch.upstreams.base.time.monotonic", lambda: current["value"])

    def fake_sleep(seconds):
        sleeps.append(seconds)
        current["value"] += seconds

    monkeypatch.setattr("releasewatch.upstreams.base.time.sleep", fake_sleep)

    def handler(request):
        return httpx.Response(
            200,
            json={
                "id": ARTIST_MBID,
                "name": "Fugazi",
                "sort-name": "Fugazi",
                "aliases": [],
            },
        )

    first_client = MusicBrainzClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    second_client = MusicBrainzClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    first_client.lookup_artist(ARTIST_MBID)
    second_client.lookup_artist(ARTIST_MBID)

    assert sleeps == [1.0]


def test_search_artists_sends_query_limit_offset_and_json_format():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "artists": [
                    {
                        "id": ARTIST_MBID,
                        "name": "Fugazi",
                        "sort-name": "Fugazi",
                        "aliases": [],
                    }
                ]
            },
        )

    client = MusicBrainzClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        throttle=_instant_throttle(),
    )

    artists = client.search_artists("artist:Fugazi", limit=7, offset=14)

    assert seen == {
        "path": "/ws/2/artist",
        "params": {
            "query": "artist:Fugazi",
            "limit": "7",
            "offset": "14",
            "fmt": "json",
        },
    }
    assert [artist.mbid for artist in artists] == [ARTIST_MBID]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_search_artists_rejects_invalid_limit_and_offset(kwargs):
    client = MusicBrainzClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
        ),
        throttle=_instant_throttle(),
    )

    with pytest.raises(ValueError):
        client.search_artists("artist:Fugazi", **kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ],
)
def test_browse_release_groups_rejects_invalid_limit_and_offset(kwargs):
    client = MusicBrainzClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))
        ),
        throttle=_instant_throttle(),
    )

    with pytest.raises(ValueError):
        client.browse_release_groups(ARTIST_MBID, **kwargs)


def test_artist_raw_payload_is_copied_before_storage():
    payload = {
        "id": ARTIST_MBID,
        "name": "Fugazi",
        "sort-name": "Fugazi",
        "aliases": [],
    }

    artist = _artist_from_payload(payload)
    payload["name"] = "Changed"

    assert artist.raw_payload["name"] == "Fugazi"


def test_release_group_raw_payload_is_copied_before_storage():
    payload = {
        "id": RELEASE_GROUP_MBID,
        "title": "Repeater",
        "primary-type": "Album",
        "secondary-types": [],
        "first-release-date": "1990",
    }

    release_group = _release_group_from_payload(payload)
    payload["title"] = "Changed"

    assert release_group.raw_payload["title"] == "Repeater"
