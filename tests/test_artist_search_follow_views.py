from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.test import Client
from django.urls import reverse

from releasewatch.models import Artist, Follow
from releasewatch.upstreams import UpstreamArtist, UpstreamUnavailable

pytestmark = pytest.mark.django_db
TEST_PASSWORD = "test-password"  # noqa: S105


@pytest.fixture(autouse=True)
def locmem_cache(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "artist-search-follow-tests",
        }
    }
    caches.close_all()
    cache.clear()
    yield
    cache.clear()
    caches.close_all()


def create_user(username="listener"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password=TEST_PASSWORD,
    )


def upstream_artist(mbid, name="Fugazi"):
    return UpstreamArtist(
        mbid=str(mbid),
        name=name,
        sort_name=name,
        disambiguation="Washington, D.C. band",
        artist_type="Group",
        country="US",
        aliases=[],
        raw_payload={"id": str(mbid), "name": name},
    )


def test_artist_search_requires_login(client):
    response = client.get(reverse("releasewatch:artist_search"))

    assert response.status_code == 302


def test_artist_search_without_query_renders_empty_form(client, mocker):
    user = create_user()
    client.force_login(user)
    search = mocker.patch("releasewatch.views.MusicBrainzClient.search_artists")

    response = client.get(reverse("releasewatch:artist_search"))

    assert response.status_code == 200
    assert b"Search artists" in response.content
    search.assert_not_called()


def test_artist_search_uses_musicbrainz_client_and_shows_results(client, mocker):
    user = create_user()
    mbid = uuid4()
    client.force_login(user)
    search = mocker.patch(
        "releasewatch.views.MusicBrainzClient.search_artists",
        return_value=[upstream_artist(mbid)],
    )

    response = client.get(reverse("releasewatch:artist_search"), {"q": "Fugazi"})

    assert response.status_code == 200
    search.assert_called_once()
    assert b"Fugazi" in response.content
    assert b"Follow Fugazi" in response.content


def test_artist_search_rate_limit_returns_429(client, mocker):
    user = create_user()
    client.force_login(user)
    mocker.patch(
        "releasewatch.views.check_rate_limit",
        return_value=mocker.Mock(allowed=False, retry_after_seconds=30),
    )

    response = client.get(reverse("releasewatch:artist_search"), {"q": "Fugazi"})

    assert response.status_code == 429
    assert b"Too many requests" in response.content


def test_artist_search_upstream_error_returns_controlled_error(client, mocker):
    user = create_user()
    client.force_login(user)
    mocker.patch(
        "releasewatch.views.MusicBrainzClient.search_artists",
        side_effect=UpstreamUnavailable("down", provider="musicbrainz"),
    )

    response = client.get(reverse("releasewatch:artist_search"), {"q": "Fugazi"})

    assert response.status_code == 503
    assert b"Artist search is temporarily unavailable." in response.content
    assert b'role="alert"' in response.content


def test_follow_artist_creates_artist_follow_and_enqueues_sync(client, mocker):
    user = create_user()
    mbid = uuid4()
    client.force_login(user)
    lookup = mocker.patch(
        "releasewatch.views.MusicBrainzClient.lookup_artist",
        return_value=upstream_artist(mbid),
    )
    delay = mocker.patch("releasewatch.views.sync_artist_releases_task.delay")

    response = client.post(reverse("releasewatch:follow_artist"), {"mbid": str(mbid)})

    assert response.status_code == 302
    lookup.assert_called_once_with(str(mbid))
    artist = Artist.objects.get(mbid=mbid)
    follow = Follow.objects.get(user=user, artist=artist)
    assert follow.is_ignored is False
    delay.assert_called_once_with(artist.id)


def test_follow_artist_invalid_form_renders_errors(client):
    user = create_user()
    client.force_login(user)

    response = client.post(reverse("releasewatch:follow_artist"), {"mbid": "bad"})

    assert response.status_code == 400
    assert b"Enter a valid UUID" in response.content
    assert b'role="alert"' in response.content


def test_follow_artist_upstream_error_returns_controlled_error(client, mocker):
    user = create_user()
    client.force_login(user)
    mocker.patch(
        "releasewatch.views.MusicBrainzClient.lookup_artist",
        side_effect=UpstreamUnavailable("down", provider="musicbrainz"),
    )

    response = client.post(reverse("releasewatch:follow_artist"), {"mbid": str(uuid4())})

    assert response.status_code == 503
    assert b"Artist follow is temporarily unavailable." in response.content
    assert b'role="alert"' in response.content


def test_follow_artist_rate_limit_backend_failure_returns_503(client, mocker):
    from releasewatch.rate_limits import RateLimitUnavailable

    user = create_user("rate-limit-failure")
    client.force_login(user)
    mocker.patch("releasewatch.views.check_rate_limit", side_effect=RateLimitUnavailable("down"))

    response = client.post(reverse("releasewatch:follow_artist"), {"mbid": str(uuid4())})

    assert response.status_code == 503
    assert b"Service temporarily unavailable" in response.content


def test_follow_artist_requires_csrf_token():
    user = create_user("csrf-user")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    response = client.post(reverse("releasewatch:follow_artist"), {"mbid": str(uuid4())})

    assert response.status_code == 403


def test_follow_artist_requires_post(client):
    user = create_user()
    client.force_login(user)

    response = client.get(reverse("releasewatch:follow_artist"))

    assert response.status_code == 405
