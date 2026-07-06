from datetime import date
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from releasewatch.models import Artist, DatePrecision, Follow, ReleaseEvent, ReleaseGroup

pytestmark = pytest.mark.django_db


def create_user(username="listener"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password="test-password",  # noqa: S106
    )


def create_artist(name="Fugazi"):
    return Artist.objects.create(mbid=uuid4(), name=name, sort_name=name)


def create_event(artist, *, event_date=date(2026, 6, 22), title="Repeater"):
    group = ReleaseGroup.objects.create(mbid=uuid4(), artist=artist, title=title)
    return ReleaseEvent.objects.create(
        release_group=group,
        event_date=event_date,
        date_precision=DatePrecision.DAY,
        visible=True,
    )


def test_dashboard_requires_login(client):
    response = client.get(reverse("releasewatch:dashboard"))

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_dashboard_shows_user_follows_and_release_events(client):
    user = create_user()
    other_user = create_user("other")
    followed = create_artist()
    other_artist = create_artist("Other")
    Follow.objects.create(user=user, artist=followed)
    Follow.objects.create(user=other_user, artist=other_artist)
    create_event(followed)
    create_event(other_artist)
    client.force_login(user)

    response = client.get(reverse("releasewatch:dashboard"))

    assert response.status_code == 200
    assert b"Dashboard" in response.content
    assert b"Fugazi" in response.content
    assert b"Repeater" in response.content
    assert b"Other" not in response.content


def test_dashboard_hides_release_events_from_ignored_follows(client):
    user = create_user()
    active = create_artist("Active Artist")
    ignored = create_artist("Ignored Artist")
    Follow.objects.create(user=user, artist=active)
    Follow.objects.create(user=user, artist=ignored, is_ignored=True)
    create_event(active)
    create_event(ignored)
    client.force_login(user)

    response = client.get(reverse("releasewatch:dashboard"))

    assert response.status_code == 200
    assert b"Active Artist" in response.content
    assert b"Ignored Artist" not in response.content


def test_dashboard_does_not_link_follow_without_visible_releases(client):
    user = create_user()
    artist = create_artist("No Releases")
    Follow.objects.create(user=user, artist=artist)
    client.force_login(user)

    response = client.get(reverse("releasewatch:dashboard"))

    assert response.status_code == 200
    assert b"No Releases" in response.content
    assert f'href="/artists/{artist.id}/"'.encode() not in response.content


def test_dashboard_shows_latest_release_events(client):
    user = create_user()
    artist = create_artist()
    Follow.objects.create(user=user, artist=artist)
    for day in range(1, 23):
        title = "Oldest release" if day == 1 else f"Release {day}"
        create_event(artist, event_date=date(2026, 6, day), title=title)
    client.force_login(user)

    response = client.get(reverse("releasewatch:dashboard"))

    assert response.status_code == 200
    assert b"Release 22" in response.content
    assert b"Oldest release" not in response.content


def test_login_route_renders_accessible_form(client):
    response = client.get("/accounts/login/", {"next": "/dashboard/"})

    assert response.status_code == 200
    assert b"Log in" in response.content
    assert b"<main" in response.content
    assert b"name=\"username\"" in response.content
    assert b"name=\"password\"" in response.content
    assert b'name="next" value="/dashboard/"' in response.content
    assert b"Open the invite link you were given." in response.content


def test_follow_list_requires_login(client):
    response = client.get(reverse("releasewatch:follow_list"))

    assert response.status_code == 302


def test_follow_list_shows_active_and_ignored_follows_for_user_only(client):
    user = create_user()
    other_user = create_user("other")
    active = create_artist("Active Artist")
    ignored = create_artist("Ignored Artist")
    other = create_artist("Other Artist")
    Follow.objects.create(user=user, artist=active)
    Follow.objects.create(user=user, artist=ignored, is_ignored=True)
    Follow.objects.create(user=other_user, artist=other)
    client.force_login(user)

    response = client.get(reverse("releasewatch:follow_list"))

    assert response.status_code == 200
    assert b"Active Artist" in response.content
    assert b"Ignored Artist" in response.content
    assert b"Other Artist" not in response.content


def test_follow_list_shows_remove_buttons_for_each_follow(client):
    user = create_user()
    active = create_artist("Active Artist")
    ignored = create_artist("Ignored Artist")
    active_follow = Follow.objects.create(user=user, artist=active)
    ignored_follow = Follow.objects.create(user=user, artist=ignored, is_ignored=True)
    client.force_login(user)

    response = client.get(reverse("releasewatch:follow_list"))

    assert response.status_code == 200
    assert (
        f'action="{reverse("releasewatch:remove_follow", args=[active_follow.id])}"'.encode()
        in response.content
    )
    assert (
        f'action="{reverse("releasewatch:remove_follow", args=[ignored_follow.id])}"'.encode()
        in response.content
    )
    assert b"Unfollow Active Artist" in response.content
    assert b"Remove Ignored Artist" in response.content


def test_remove_follow_unfollows_active_artist_without_deleting_artist(client):
    user = create_user()
    artist = create_artist()
    follow = Follow.objects.create(user=user, artist=artist)
    client.force_login(user)

    response = client.post(reverse("releasewatch:remove_follow", args=[follow.id]))

    assert response.status_code == 302
    assert response["Location"] == reverse("releasewatch:follow_list")
    assert not Follow.objects.filter(pk=follow.id).exists()
    assert Artist.objects.filter(pk=artist.id).exists()


def test_remove_follow_removes_ignored_artist_without_deleting_artist(client):
    user = create_user()
    artist = create_artist("Ignored Artist")
    follow = Follow.objects.create(user=user, artist=artist, is_ignored=True)
    client.force_login(user)

    response = client.post(reverse("releasewatch:remove_follow", args=[follow.id]))

    assert response.status_code == 302
    assert response["Location"] == reverse("releasewatch:follow_list")
    assert not Follow.objects.filter(pk=follow.id).exists()
    assert Artist.objects.filter(pk=artist.id).exists()


def test_remove_follow_protects_other_users_follows(client):
    user = create_user()
    other_user = create_user("other")
    artist = create_artist("Other Artist")
    follow = Follow.objects.create(user=other_user, artist=artist)
    client.force_login(user)

    response = client.post(reverse("releasewatch:remove_follow", args=[follow.id]))

    assert response.status_code == 404
    assert Follow.objects.filter(pk=follow.id, user=other_user).exists()
    assert Artist.objects.filter(pk=artist.id).exists()


def test_remove_follow_requires_post(client):
    user = create_user()
    artist = create_artist()
    follow = Follow.objects.create(user=user, artist=artist)
    client.force_login(user)

    response = client.get(reverse("releasewatch:remove_follow", args=[follow.id]))

    assert response.status_code == 405


def test_remove_follow_requires_csrf_token():
    user = create_user("csrf-user")
    artist = create_artist()
    follow = Follow.objects.create(user=user, artist=artist)
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    response = client.post(reverse("releasewatch:remove_follow", args=[follow.id]))

    assert response.status_code == 403
