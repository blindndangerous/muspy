from datetime import date
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from releasewatch.models import Artist, DatePrecision, ReleaseEvent, ReleaseGroup, StarredRelease

pytestmark = pytest.mark.django_db


def create_user(username="listener"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.com",
    )


def create_event(*, visible=True, title="Repeater", artist_name="Fugazi"):
    artist = Artist.objects.create(mbid=uuid4(), name=artist_name, sort_name=artist_name)
    group = ReleaseGroup.objects.create(
        mbid=uuid4(),
        artist=artist,
        title=title,
        primary_type="Album",
    )
    return ReleaseEvent.objects.create(
        release_group=group,
        event_date=date(2026, 6, 22),
        date_precision=DatePrecision.DAY,
        visible=visible,
    )


def test_authenticated_user_can_star_visible_release(client):
    user = create_user()
    event = create_event()
    client.force_login(user)

    response = client.post(reverse("releasewatch:star_release", args=[event.id]))

    assert response.status_code == 302
    assert StarredRelease.objects.filter(user=user, release_event=event).exists()


def test_repeated_star_is_idempotent(client):
    user = create_user()
    event = create_event()
    client.force_login(user)
    url = reverse("releasewatch:star_release", args=[event.id])

    client.post(url)
    response = client.post(url)

    assert response.status_code == 302
    assert StarredRelease.objects.filter(user=user, release_event=event).count() == 1


def test_authenticated_user_can_unstar_release_idempotently(client):
    user = create_user()
    event = create_event()
    StarredRelease.objects.create(user=user, release_event=event)
    client.force_login(user)
    url = reverse("releasewatch:unstar_release", args=[event.id])

    first_response = client.post(url)
    second_response = client.post(url)

    assert first_response.status_code == 302
    assert second_response.status_code == 302
    assert not StarredRelease.objects.filter(user=user, release_event=event).exists()


def test_star_actions_require_login(client):
    event = create_event()

    response = client.post(reverse("releasewatch:star_release", args=[event.id]))

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]
    assert not StarredRelease.objects.exists()


def test_star_actions_are_post_only_for_authenticated_users(client):
    user = create_user()
    event = create_event()
    client.force_login(user)

    star_response = client.get(reverse("releasewatch:star_release", args=[event.id]))
    unstar_response = client.get(reverse("releasewatch:unstar_release", args=[event.id]))

    assert star_response.status_code == 405
    assert unstar_response.status_code == 405
    assert not StarredRelease.objects.exists()


def test_invisible_release_cannot_be_starred(client):
    user = create_user()
    event = create_event(visible=False)
    client.force_login(user)

    response = client.post(reverse("releasewatch:star_release", args=[event.id]))

    assert response.status_code == 404
    assert not StarredRelease.objects.exists()


def test_starred_release_list_requires_login(client):
    response = client.get(reverse("releasewatch:starred_release_list"))

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_starred_release_list_is_private_to_authenticated_user(client):
    user = create_user()
    other_user = create_user("other")
    own_event = create_event(title="Own Star")
    other_event = create_event(title="Other Star", artist_name="Minor Threat")
    StarredRelease.objects.create(user=user, release_event=own_event)
    StarredRelease.objects.create(user=other_user, release_event=other_event)
    client.force_login(user)

    response = client.get(reverse("releasewatch:starred_release_list"))

    assert response.status_code == 200
    assert b"Own Star" in response.content
    assert b"Other Star" not in response.content


def test_unstar_does_not_remove_another_users_star(client):
    user = create_user()
    other_user = create_user("other")
    event = create_event()
    StarredRelease.objects.create(user=other_user, release_event=event)
    client.force_login(user)

    response = client.post(reverse("releasewatch:unstar_release", args=[event.id]))

    assert response.status_code == 302
    assert StarredRelease.objects.filter(user=other_user, release_event=event).exists()


def test_anonymous_release_detail_remains_public(client):
    event = create_event()

    response = client.get(reverse("releasewatch:release_detail", args=[event.id]))

    assert response.status_code == 200
    assert b"Repeater" in response.content
    assert b"Star release" not in response.content


def test_release_pages_have_accessible_star_controls_for_authenticated_users(client):
    user = create_user()
    event = create_event()
    StarredRelease.objects.create(user=user, release_event=event)
    client.force_login(user)

    list_response = client.get(reverse("releasewatch:release_list"))
    detail_response = client.get(reverse("releasewatch:release_detail", args=[event.id]))
    starred_response = client.get(reverse("releasewatch:starred_release_list"))

    assert b'aria-label="Unstar Repeater by Fugazi"' in list_response.content
    assert b'aria-label="Unstar Repeater by Fugazi"' in detail_response.content
    assert b'aria-label="Unstar Repeater by Fugazi"' in starred_response.content
