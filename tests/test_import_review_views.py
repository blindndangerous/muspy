from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.urls import reverse

from releasewatch.models import Artist, Follow, ImportCandidate, ImportRun

pytestmark = pytest.mark.django_db
TEST_PASSWORD = "test-password"  # noqa: S105


@pytest.fixture(autouse=True)
def locmem_cache(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "import-review-tests",
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


def create_run(user):
    return ImportRun.objects.create(
        user=user,
        source=ImportRun.Source.PLAIN_TEXT,
        status=ImportRun.Status.PENDING_REVIEW,
    )


def create_candidate(run, artist=None):
    return ImportCandidate.objects.create(
        import_run=run,
        artist=artist,
        source_name=artist.name if artist else "Unknown Artist",
        source_identifier=f"plain:{uuid4()}",
    )


def test_import_list_requires_login(client):
    response = client.get(reverse("releasewatch:import_list"))
    assert response.status_code == 302


def test_import_list_shows_only_current_user_runs(client):
    user = create_user()
    other = create_user("other")
    create_run(user)
    create_run(other)
    client.force_login(user)

    response = client.get(reverse("releasewatch:import_list"))

    assert response.status_code == 200
    assert response.content.count(b"Plain text") == 1


def test_import_detail_blocks_cross_user_access(client):
    user = create_user()
    other = create_user("other")
    run = create_run(other)
    client.force_login(user)

    response = client.get(reverse("releasewatch:import_detail", args=[run.id]))

    assert response.status_code == 404


def test_accept_import_candidate_creates_follow_and_marks_candidate(client, mocker):
    user = create_user()
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    run = create_run(user)
    candidate = create_candidate(run, artist)
    client.force_login(user)
    delay = mocker.patch("releasewatch.views.sync_artist_releases_task.delay")

    response = client.post(
        reverse("releasewatch:review_import_candidate", args=[candidate.id]),
        {"action": "accept"},
    )

    assert response.status_code == 302
    candidate.refresh_from_db()
    assert candidate.review_state == ImportCandidate.ReviewState.ACCEPTED
    assert Follow.objects.filter(user=user, artist=artist, is_ignored=False).exists()
    delay.assert_called_once_with(artist.id)


def test_accept_unmatched_import_candidate_redirects_without_crashing(client, mocker):
    user = create_user()
    run = create_run(user)
    candidate = create_candidate(run)
    client.force_login(user)
    delay = mocker.patch("releasewatch.views.sync_artist_releases_task.delay")

    response = client.post(
        reverse("releasewatch:review_import_candidate", args=[candidate.id]),
        {"action": "accept"},
    )

    assert response.status_code == 302
    candidate.refresh_from_db()
    assert candidate.review_state == ImportCandidate.ReviewState.PENDING
    assert not Follow.objects.filter(user=user).exists()
    delay.assert_not_called()


def test_ignore_import_candidate_marks_follow_ignored(client):
    user = create_user()
    artist = Artist.objects.create(mbid=uuid4(), name="Unwanted")
    run = create_run(user)
    candidate = create_candidate(run, artist)
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:review_import_candidate", args=[candidate.id]),
        {"action": "ignore"},
    )

    assert response.status_code == 302
    candidate.refresh_from_db()
    assert candidate.review_state == ImportCandidate.ReviewState.IGNORED
    assert Follow.objects.filter(user=user, artist=artist, is_ignored=True).exists()


def test_review_import_candidate_requires_post(client):
    user = create_user()
    run = create_run(user)
    candidate = create_candidate(run)
    client.force_login(user)

    response = client.get(reverse("releasewatch:review_import_candidate", args=[candidate.id]))

    assert response.status_code == 405
