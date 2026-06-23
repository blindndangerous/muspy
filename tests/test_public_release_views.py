from datetime import date
from uuid import uuid4

import pytest
from django.urls import reverse

from releasewatch.models import Artist, DatePrecision, ReleaseEvent, ReleaseGroup

pytestmark = pytest.mark.django_db


def create_event(*, visible=True, event_date=date(2026, 6, 22), artist_name="Fugazi"):
    artist = Artist.objects.create(mbid=uuid4(), name=artist_name, sort_name=artist_name)
    group = ReleaseGroup.objects.create(
        mbid=uuid4(),
        artist=artist,
        title="Repeater",
        primary_type="Album",
    )
    event = ReleaseEvent.objects.create(
        release_group=group,
        event_date=event_date,
        date_precision=DatePrecision.DAY if event_date else "",
        visible=visible,
    )
    return artist, group, event


def test_home_page_is_public_and_lists_visible_releases(client):
    artist, _, event = create_event()
    create_event(visible=False)

    response = client.get(reverse("releasewatch:home"))

    assert response.status_code == 200
    assert b"Release overview" in response.content
    assert artist.name.encode() in response.content
    assert str(event.release_group).encode() in response.content
    assert response.content.count(b"Repeater") == 1


def test_release_list_is_public_and_hides_invisible_events(client):
    create_event()
    hidden_artist, _, _ = create_event(visible=False, artist_name="Hidden Artist")

    response = client.get(reverse("releasewatch:release_list"))

    assert response.status_code == 200
    assert b"Releases" in response.content
    assert b"Repeater" in response.content
    assert hidden_artist.name.encode() not in response.content
    assert b"<caption>Visible release events</caption>" in response.content


def test_artist_detail_is_public_and_lists_visible_events(client):
    artist, _, _ = create_event()

    response = client.get(reverse("releasewatch:artist_detail", args=[artist.id]))

    assert response.status_code == 200
    assert artist.name.encode() in response.content
    assert b"Repeater" in response.content


def test_artist_detail_returns_404_when_artist_has_no_visible_events(client):
    artist, _, _ = create_event(visible=False)

    response = client.get(reverse("releasewatch:artist_detail", args=[artist.id]))

    assert response.status_code == 404


def test_release_detail_is_public_for_visible_event(client):
    _, _, event = create_event()

    response = client.get(reverse("releasewatch:release_detail", args=[event.id]))

    assert response.status_code == 200
    assert b"Repeater" in response.content
    assert b"June 22, 2026" in response.content


def test_release_detail_returns_404_for_invisible_event(client):
    _, _, event = create_event(visible=False)

    response = client.get(reverse("releasewatch:release_detail", args=[event.id]))

    assert response.status_code == 404
