from datetime import date
from uuid import uuid4

import httpx
import pytest
from django.urls import reverse

from releasewatch.images import artist_image_url, release_cover_art_url
from releasewatch.models import Artist, DatePrecision, Release, ReleaseEvent, ReleaseGroup
from releasewatch.upstreams.musicbrainz import MusicBrainzClient

pytestmark = pytest.mark.django_db

USER_AGENT = "muspy-test/1.0 (https://example.invalid/contact)"
ARTIST_MBID = "0b7f80cf-65c3-4d40-99ca-775f7d30c079"


def create_event(
    *,
    artist_raw_payload=None,
    group_raw_payload=None,
    release_raw_payload=None,
    with_release=True,
):
    artist = Artist.objects.create(
        mbid=uuid4(),
        name="Fugazi",
        sort_name="Fugazi",
        raw_payload=artist_raw_payload or {},
    )
    group = ReleaseGroup.objects.create(
        mbid=uuid4(),
        artist=artist,
        title="Repeater",
        primary_type="Album",
        raw_payload=group_raw_payload or {},
    )
    release = None
    if with_release:
        release = Release.objects.create(
            mbid=uuid4(),
            release_group=group,
            status="Official",
            raw_payload=release_raw_payload or {},
        )
    event = ReleaseEvent.objects.create(
        release_group=group,
        release=release,
        event_date=date(2026, 6, 22),
        date_precision=DatePrecision.DAY,
        visible=True,
    )
    return artist, group, release, event


def test_release_cover_art_url_uses_cover_art_archive_release_front_image():
    _, _, release, event = create_event(
        release_raw_payload={"cover-art-archive": {"front": True, "artwork": True}}
    )

    assert release_cover_art_url(event) == (
        f"https://coverartarchive.org/release/{release.mbid}/front-500"
    )


def test_release_cover_art_url_falls_back_to_release_group_front_image():
    _, group, _, event = create_event(
        with_release=False,
        group_raw_payload={"cover-art-archive": {"front": True, "artwork": True}},
    )

    assert release_cover_art_url(event) == (
        f"https://coverartarchive.org/release-group/{group.mbid}/front-500"
    )


def test_artist_image_url_uses_musicbrainz_image_relation():
    artist, _, _, _ = create_event(
        artist_raw_payload={
            "relations": [
                {
                    "target-type": "url",
                    "type": "image",
                    "url": {"resource": "https://upload.wikimedia.org/fugazi.jpg"},
                }
            ]
        }
    )

    assert artist_image_url(artist) == "https://upload.wikimedia.org/fugazi.jpg"


@pytest.mark.parametrize(
    "resource",
    [
        "http://upload.wikimedia.org/fugazi.jpg",
        "https://example.com/fugazi.jpg",
    ],
)
def test_artist_image_url_rejects_untrusted_urls(resource):
    artist, _, _, _ = create_event(
        artist_raw_payload={
            "relations": [
                {
                    "target-type": "url",
                    "type": "image",
                    "url": {"resource": resource},
                }
            ]
        }
    )

    assert artist_image_url(artist) is None


def test_release_cover_art_url_rejects_untrusted_payload_image_urls():
    _, _, _, event = create_event(
        release_raw_payload={
            "images": [
                {
                    "front": True,
                    "thumbnails": {"500": "https://example.com/front.jpg"},
                    "image": "https://example.com/full.jpg",
                }
            ]
        }
    )

    assert release_cover_art_url(event) is None


def test_release_cover_art_url_accepts_cover_art_archive_payload_image_urls():
    _, _, _, event = create_event(
        release_raw_payload={
            "images": [
                {
                    "front": True,
                    "thumbnails": {
                        "500": "https://archive.org/download/mbid/front-500.jpg",
                    },
                }
            ]
        }
    )

    assert release_cover_art_url(event) == "https://archive.org/download/mbid/front-500.jpg"


def test_release_cover_art_url_ignores_non_front_or_malformed_images():
    _, _, _, event = create_event(
        release_raw_payload={
            "images": [
                {"front": False, "thumbnails": {"500": "https://archive.org/back.jpg"}},
                "not-an-image-payload",
            ]
        },
        group_raw_payload={"images": "not-a-list"},
    )

    assert release_cover_art_url(event) is None


def test_artist_image_url_accepts_direct_trusted_image():
    artist, _, _, _ = create_event(
        artist_raw_payload={"image_url": "https://commons.wikimedia.org/fugazi.jpg"}
    )

    assert artist_image_url(artist) == "https://commons.wikimedia.org/fugazi.jpg"


def test_artist_image_url_ignores_malformed_relations():
    artist, _, _, _ = create_event(
        artist_raw_payload={
            "image": {"resource": "https://upload.wikimedia.org/fugazi.jpg"},
            "relations": [
                {"target-type": "artist", "type": "image"},
                "not-a-relation-payload",
            ],
        }
    )

    assert artist_image_url(artist) is None


def test_musicbrainz_lookup_artist_requests_url_relations_for_artist_images():
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "id": ARTIST_MBID,
                "name": "Fugazi",
                "sort-name": "Fugazi",
                "aliases": [],
                "relations": [
                    {
                        "target-type": "url",
                        "type": "image",
                        "url": {"resource": "https://upload.wikimedia.org/fugazi.jpg"},
                    }
                ],
            },
        )

    client = MusicBrainzClient(
        user_agent=USER_AGENT,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        throttle=None,
    )

    artist = client.lookup_artist(ARTIST_MBID)

    assert seen["params"]["inc"] == "aliases+url-rels"
    assert artist_image_url(artist) == "https://upload.wikimedia.org/fugazi.jpg"


def test_release_detail_uses_accessible_cover_art_fallback_when_missing(client):
    _, _, _, event = create_event()

    response = client.get(reverse("releasewatch:release_detail", args=[event.id]))

    assert response.status_code == 200
    assert b"No cover art available for Repeater." in response.content
    assert b"<img" not in response.content


def test_artist_detail_uses_accessible_artist_image_fallback_when_missing(client):
    artist, _, _, _ = create_event()

    response = client.get(reverse("releasewatch:artist_detail", args=[artist.id]))

    assert response.status_code == 200
    assert b"No artist image available for Fugazi." in response.content
    assert b"<img" not in response.content


def test_release_and_artist_detail_images_have_meaningful_alt_text(client):
    artist, _, _, event = create_event(
        artist_raw_payload={
            "relations": [
                {
                    "target-type": "url",
                    "type": "image",
                    "url": {"resource": "https://upload.wikimedia.org/fugazi.jpg"},
                }
            ]
        },
        release_raw_payload={"cover-art-archive": {"front": True}},
    )

    release_response = client.get(reverse("releasewatch:release_detail", args=[event.id]))
    artist_response = client.get(reverse("releasewatch:artist_detail", args=[artist.id]))

    assert b'alt="Cover art for Repeater by Fugazi"' in release_response.content
    assert b'alt="Artist image for Fugazi"' in artist_response.content


def test_release_and_artist_detail_images_do_not_send_referrers(client):
    artist, _, _, event = create_event(
        artist_raw_payload={
            "relations": [
                {
                    "target-type": "url",
                    "type": "image",
                    "url": {"resource": "https://upload.wikimedia.org/fugazi.jpg"},
                }
            ]
        },
        release_raw_payload={"cover-art-archive": {"front": True}},
    )

    release_response = client.get(reverse("releasewatch:release_detail", args=[event.id]))
    artist_response = client.get(reverse("releasewatch:artist_detail", args=[artist.id]))

    assert b'referrerpolicy="no-referrer"' in release_response.content
    assert b'referrerpolicy="no-referrer"' in artist_response.content
