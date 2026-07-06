from datetime import UTC, date, datetime, timedelta
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


def create_release_event(
    *,
    artist=None,
    artist_name="Fugazi",
    title="Repeater",
    visible=True,
    event_date=date(1990, 4, 19),
    updated_at=None,
):
    if artist is None:
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
        title=title,
        primary_type="Album",
        secondary_types=["Studio"],
        first_release_date=event_date,
        first_release_precision=DatePrecision.DAY,
        raw_payload={"feed_token": "group-secret"},
    )
    release = Release.objects.create(
        mbid=uuid4(),
        release_group=group,
        country="US",
        release_date=event_date,
        release_date_precision=DatePrecision.DAY,
        status="Official",
        media_format="CD",
        raw_payload={"notification_setting": "release-secret"},
    )
    event = ReleaseEvent.objects.create(
        release_group=group,
        release=release,
        country="US",
        event_date=event_date,
        date_precision=DatePrecision.DAY,
        visible=visible,
    )
    if updated_at is not None:
        ReleaseEvent.objects.filter(pk=event.pk).update(updated_at=updated_at)
        event.refresh_from_db()
    return artist, group, release, event


def release_titles(response):
    return [release["title"] for release in response.json()["releases"]]


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


def test_release_list_limit_controls_page_size(client):
    for index in range(3):
        create_release_event(title=f"Release {index}")

    response = client.get(reverse("releasewatch:api_v1_release_list"), {"limit": "2"})

    assert response.status_code == 200
    assert release_titles(response) == ["Release 0", "Release 1"]


def test_release_list_limit_is_capped_at_100(client):
    for index in range(101):
        create_release_event(title=f"Release {index:03d}")

    response = client.get(reverse("releasewatch:api_v1_release_list"), {"limit": "500"})

    assert response.status_code == 200
    releases = response.json()["releases"]
    assert len(releases) == 100
    assert releases[-1]["title"] == "Release 099"


def test_release_list_offset_skips_visible_releases(client):
    for index in range(3):
        create_release_event(title=f"Release {index}")

    response = client.get(
        reverse("releasewatch:api_v1_release_list"),
        {"limit": "1", "offset": "1"},
    )

    assert response.status_code == 200
    assert release_titles(response) == ["Release 1"]


def test_release_list_rejects_huge_offset(client):
    response = client.get(
        reverse("releasewatch:api_v1_release_list"),
        {"offset": "10001"},
    )

    assert response.status_code == 400
    assert response.headers["Content-Type"] == "application/json"
    assert "offset" in response.json()["errors"]
    assert b"Traceback" not in response.content


def test_release_list_filters_by_artist_mbid(client):
    target_artist = Artist.objects.create(mbid=uuid4(), name="Fugazi", sort_name="Fugazi")
    other_artist = Artist.objects.create(
        mbid=uuid4(),
        name="Minor Threat",
        sort_name="Minor Threat",
    )
    create_release_event(artist=target_artist, title="Repeater")
    create_release_event(artist=other_artist, title="Out of Step")

    response = client.get(
        reverse("releasewatch:api_v1_release_list"),
        {"artist_mbid": str(target_artist.mbid)},
    )

    assert response.status_code == 200
    assert release_titles(response) == ["Repeater"]


def test_release_list_filters_by_since_datetime(client):
    old_updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    new_updated_at = old_updated_at + timedelta(days=1)
    create_release_event(title="Old update", updated_at=old_updated_at)
    create_release_event(title="New update", updated_at=new_updated_at)

    response = client.get(
        reverse("releasewatch:api_v1_release_list"),
        {"since": (old_updated_at + timedelta(hours=1)).isoformat()},
    )

    assert response.status_code == 200
    assert release_titles(response) == ["New update"]


@pytest.mark.parametrize(
    ("param", "value"),
    [
        ("limit", "0"),
        ("limit", "not-a-number"),
        ("offset", "-1"),
        ("artist_mbid", "not-a-mbid"),
        ("since", "not-a-datetime"),
    ],
)
def test_release_list_invalid_params_return_json_400(client, param, value):
    response = client.get(reverse("releasewatch:api_v1_release_list"), {param: value})

    assert response.status_code == 400
    assert response.headers["Content-Type"] == "application/json"
    assert param in response.json()["errors"]
    assert b"Traceback" not in response.content


def test_release_list_excludes_private_fields_and_values(client):
    artist, _, _, _ = create_release_event()
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

    response = client.get(
        reverse("releasewatch:api_v1_release_list"),
        {"artist_mbid": str(artist.mbid)},
    )

    assert response.status_code == 200
    lowered_values = {value.lower() for value in flatten_json(response.json())}
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


def test_release_list_rejects_post(client):
    response = client.post(reverse("releasewatch:api_v1_release_list"))

    assert response.status_code == 405


def test_release_event_indexes_visible_updated_at_for_public_since_filter():
    assert any(index.fields == ["visible", "updated_at"] for index in ReleaseEvent._meta.indexes)
