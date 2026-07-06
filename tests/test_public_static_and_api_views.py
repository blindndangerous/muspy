from datetime import date
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from releasewatch.models import (
    Artist,
    DatePrecision,
    FeedToken,
    ImportRun,
    NotificationPreference,
    Release,
    ReleaseEvent,
    ReleaseGroup,
)

pytestmark = pytest.mark.django_db


def create_public_release(*, visible=True, artist_name="Fugazi"):
    artist = Artist.objects.create(
        mbid=uuid4(),
        name=artist_name,
        sort_name=artist_name,
        disambiguation="Washington, D.C. post-hardcore band",
        artist_type="Group",
        country="US",
        raw_payload={"email": "artist-private@example.com", "token": "artist-secret"},
    )
    group = ReleaseGroup.objects.create(
        mbid=uuid4(),
        artist=artist,
        title="Repeater",
        primary_type="Album",
        secondary_types=["Studio"],
        first_release_date=date(1990, 4, 19),
        first_release_precision=DatePrecision.DAY,
        raw_payload={"feed_token": "group-secret"},
    )
    release = Release.objects.create(
        mbid=uuid4(),
        release_group=group,
        country="US",
        release_date=date(1990, 4, 19),
        release_date_precision=DatePrecision.DAY,
        status="Official",
        media_format="CD",
        raw_payload={"notification_setting": "release-secret"},
    )
    event = ReleaseEvent.objects.create(
        release_group=group,
        release=release,
        country="US",
        event_date=date(1990, 4, 19),
        date_precision=DatePrecision.DAY,
        visible=visible,
    )
    return artist, group, release, event


def flatten_json(value):
    if isinstance(value, dict):
        items = []
        for key, child in value.items():
            items.append(str(key))
            items.extend(flatten_json(child))
        return items
    if isinstance(value, list):
        items = []
        for child in value:
            items.extend(flatten_json(child))
        return items
    return [str(value)]


@pytest.mark.parametrize(
    ("route_name", "heading"),
    [
        ("releasewatch:about", b"About Muspy"),
        ("releasewatch:faq", b"Frequently Asked Questions"),
        ("releasewatch:contact", b"Contact"),
    ],
)
def test_public_static_pages_render(client, route_name, heading):
    response = client.get(reverse(route_name))

    assert response.status_code == 200
    assert heading in response.content


def test_sitemap_renders_xml_with_public_routes(client):
    response = client.get(reverse("releasewatch:sitemap"))

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/xml; charset=utf-8"
    assert b"<urlset" in response.content
    assert b"/about/" in response.content
    assert b"/faq/" in response.content
    assert b"/contact/" in response.content
    assert b"/releases/" in response.content
    assert b"/api/v1/releases/" in response.content


def test_public_api_release_list_returns_visible_release_data(client):
    artist, group, release, event = create_public_release()
    hidden_artist, _, _, _ = create_public_release(
        visible=False,
        artist_name="Hidden Artist",
    )

    response = client.get(reverse("releasewatch:api_v1_release_list"))

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert response.json() == {
        "releases": [
            {
                "id": event.id,
                "mbid": str(group.mbid),
                "title": "Repeater",
                "primary_type": "Album",
                "secondary_types": ["Studio"],
                "date": "1990-04-19",
                "date_precision": DatePrecision.DAY,
                "country": "US",
                "artist": {
                    "mbid": str(artist.mbid),
                    "name": "Fugazi",
                    "sort_name": "Fugazi",
                    "disambiguation": "Washington, D.C. post-hardcore band",
                },
                "release": {
                    "mbid": str(release.mbid),
                    "country": "US",
                    "date": "1990-04-19",
                    "date_precision": DatePrecision.DAY,
                    "status": "Official",
                    "media_format": "CD",
                },
            }
        ]
    }
    assert hidden_artist.name not in str(response.json())


def test_public_api_artist_detail_returns_visible_artist_data(client):
    artist, group, _, event = create_public_release()

    response = client.get(reverse("releasewatch:api_v1_artist_detail", args=[artist.mbid]))

    assert response.status_code == 200
    assert response.json() == {
        "artist": {
            "mbid": str(artist.mbid),
            "name": "Fugazi",
            "sort_name": "Fugazi",
            "disambiguation": "Washington, D.C. post-hardcore band",
            "type": "Group",
            "country": "US",
            "releases": [
                {
                    "id": event.id,
                    "mbid": str(group.mbid),
                    "title": "Repeater",
                    "primary_type": "Album",
                    "secondary_types": ["Studio"],
                    "date": "1990-04-19",
                    "date_precision": DatePrecision.DAY,
                    "country": "US",
                }
            ],
        }
    }


def test_public_api_release_list_serializes_missing_release_and_unknown_dates(client):
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi", sort_name="Fugazi")
    group = ReleaseGroup.objects.create(
        mbid=uuid4(),
        artist=artist,
        title="Unknown Pleasures",
        primary_type="Album",
    )
    event = ReleaseEvent.objects.create(
        release_group=group,
        release=None,
        visible=True,
    )

    response = client.get(reverse("releasewatch:api_v1_release_list"))

    release_payload = response.json()["releases"][0]
    assert release_payload["id"] == event.id
    assert release_payload["release"] is None
    assert release_payload["date"] is None


def test_public_api_artist_detail_caps_visible_releases(client):
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi", sort_name="Fugazi")
    for index in range(101):
        group = ReleaseGroup.objects.create(
            mbid=uuid4(),
            artist=artist,
            title=f"Release {index:03d}",
            primary_type="Album",
        )
        ReleaseEvent.objects.create(
            release_group=group,
            event_date=date(1990, 4, 19),
            date_precision=DatePrecision.DAY,
            visible=True,
        )

    response = client.get(reverse("releasewatch:api_v1_artist_detail", args=[artist.mbid]))

    releases = response.json()["artist"]["releases"]
    release_titles = {release["title"] for release in releases}
    assert len(releases) == 100
    assert "Release 000" in release_titles
    assert "Release 100" not in release_titles


def test_public_api_v1_endpoints_are_read_only(client):
    artist, _, _, _ = create_public_release()

    release_response = client.post(reverse("releasewatch:api_v1_release_list"))
    artist_response = client.post(
        reverse("releasewatch:api_v1_artist_detail", args=[artist.mbid])
    )

    assert release_response.status_code == 405
    assert artist_response.status_code == 405


def test_public_api_excludes_private_fields_and_values(client):
    create_public_release()
    user = get_user_model().objects.create_user(
        username="listener",
        email="listener@example.com",
    )
    FeedToken.objects.create(
        user=user,
        feed_type=FeedToken.FeedType.RSS,
        token_hash="a" * 64,
        name="Private feed",
    )
    NotificationPreference.objects.create(user=user, email_enabled=False)
    ImportRun.objects.create(
        user=user,
        source=ImportRun.Source.LASTFM,
        raw_payload={"username": "private-lastfm", "token": "private-token"},
    )

    release_response = client.get(reverse("releasewatch:api_v1_release_list"))
    artist_response = client.get(
        reverse(
            "releasewatch:api_v1_artist_detail",
            args=[Artist.objects.get(name="Fugazi").mbid],
        )
    )

    for response in [release_response, artist_response]:
        values = flatten_json(response.json())
        lowered_values = {value.lower() for value in values}
        assert "email" not in lowered_values
        assert "feed_token" not in lowered_values
        assert "token" not in lowered_values
        assert "raw_payload" not in lowered_values
        assert "notification_setting" not in lowered_values
        assert "notification" not in lowered_values
        assert "imports" not in lowered_values
        assert "listener@example.com" not in lowered_values
        assert "private feed" not in lowered_values
        assert "private-lastfm" not in lowered_values
        assert "private-token" not in lowered_values
        assert "artist-private@example.com" not in lowered_values
        assert "artist-secret" not in lowered_values
        assert "group-secret" not in lowered_values
        assert "release-secret" not in lowered_values
