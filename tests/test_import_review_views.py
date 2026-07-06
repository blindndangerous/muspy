from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.test import Client
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


def test_import_list_shows_start_import_forms(client):
    user = create_user()
    client.force_login(user)

    response = client.get(reverse("releasewatch:import_list"))

    assert response.status_code == 200
    assert b"Artist names" in response.content
    assert b"Last.fm username" in response.content
    assert b"ListenBrainz username" in response.content
    assert b"ListenBrainz user token" in response.content


def test_plain_text_import_post_creates_started_run_and_enqueues_task(client, mocker):
    user = create_user()
    client.force_login(user)
    delay = mocker.patch("releasewatch.views.run_import_task.delay")

    response = client.post(
        reverse("releasewatch:import_list"),
        {
            "source": "plain_text",
            "plain_text-artist_names": "Fugazi\nUnwound",
        },
    )

    run = ImportRun.objects.get(user=user)
    assert response.status_code == 302
    assert response.url == reverse("releasewatch:import_detail", args=[run.id])
    assert run.source == ImportRun.Source.PLAIN_TEXT
    assert run.status == ImportRun.Status.STARTED
    assert run.raw_payload == {"text": "Fugazi\nUnwound"}
    assert run.candidates.count() == 0
    delay.assert_called_once_with(run.id)


def test_plain_text_import_rejects_too_many_artist_lines(client):
    user = create_user()
    client.force_login(user)
    artist_names = "\n".join(f"Artist {index}" for index in range(501))

    response = client.post(
        reverse("releasewatch:import_list"),
        {
            "source": "plain_text",
            "plain_text-artist_names": artist_names,
        },
    )

    assert response.status_code == 400
    assert b'role="alert"' in response.content
    assert b"Enter 500 or fewer artist names." in response.content
    assert ImportRun.objects.filter(user=user).count() == 0


def test_plain_text_import_rejects_too_many_characters(client):
    user = create_user()
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:import_list"),
        {
            "source": "plain_text",
            "plain_text-artist_names": "A" * 20001,
        },
    )

    assert response.status_code == 400
    assert b'role="alert"' in response.content
    assert b"Ensure this value has at most 20000 characters." in response.content
    assert ImportRun.objects.filter(user=user).count() == 0


def test_lastfm_import_post_creates_run_and_enqueues_task(client, mocker):
    user = create_user()
    client.force_login(user)
    delay = mocker.patch("releasewatch.views.run_import_task.delay")

    response = client.post(
        reverse("releasewatch:import_list"),
        {
            "source": "lastfm",
            "lastfm-username": "last-listener",
        },
    )

    run = ImportRun.objects.get(user=user)
    assert response.status_code == 302
    assert response.url == reverse("releasewatch:import_detail", args=[run.id])
    assert run.source == ImportRun.Source.LASTFM
    assert run.status == ImportRun.Status.STARTED
    assert run.raw_payload == {"username": "last-listener"}
    delay.assert_called_once_with(run.id)


def test_listenbrainz_import_post_creates_run_with_encrypted_token_and_enqueues_task(
    client,
    settings,
    mocker,
):
    from cryptography.fernet import Fernet

    from releasewatch.provider_tokens import decrypt_provider_token

    settings.PROVIDER_TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    user = create_user()
    client.force_login(user)
    delay = mocker.patch("releasewatch.views.run_import_task.delay")

    response = client.post(
        reverse("releasewatch:import_list"),
        {
            "source": "listenbrainz",
            "listenbrainz-username": "brainz-listener",
            "listenbrainz-token": "private-token",
        },
    )

    run = ImportRun.objects.get(user=user)
    assert response.status_code == 302
    assert response.url == reverse("releasewatch:import_detail", args=[run.id])
    assert run.source == ImportRun.Source.LISTENBRAINZ
    assert run.status == ImportRun.Status.STARTED
    assert run.raw_payload["username"] == "brainz-listener"
    assert run.raw_payload["token_encrypted"] != "private-token"  # noqa: S105
    assert decrypt_provider_token(run.raw_payload["token_encrypted"]) == "private-token"
    delay.assert_called_once_with(run.id)


def test_listenbrainz_import_requires_token(client):
    user = create_user()
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:import_list"),
        {
            "source": "listenbrainz",
            "listenbrainz-username": "brainz-listener",
        },
    )

    assert response.status_code == 400
    assert b'role="alert"' in response.content
    assert b"This field is required." in response.content
    assert ImportRun.objects.filter(user=user).count() == 0


def test_listenbrainz_import_rejects_too_long_token(client):
    user = create_user()
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:import_list"),
        {
            "source": "listenbrainz",
            "listenbrainz-username": "brainz-listener",
            "listenbrainz-token": "t" * 4097,
        },
    )

    assert response.status_code == 400
    assert b'role="alert"' in response.content
    assert b"Ensure this value has at most 4096 characters." in response.content
    assert ImportRun.objects.filter(user=user).count() == 0


def test_listenbrainz_import_without_token_encryption_key_renders_alert(
    client,
    settings,
    mocker,
):
    settings.PROVIDER_TOKEN_ENCRYPTION_KEY = ""
    user = create_user()
    client.force_login(user)
    delay = mocker.patch("releasewatch.views.run_import_task.delay")

    response = client.post(
        reverse("releasewatch:import_list"),
        {
            "source": "listenbrainz",
            "listenbrainz-username": "brainz-listener",
            "listenbrainz-token": "private-token",
        },
    )

    assert response.status_code == 503
    assert b'role="alert"' in response.content
    assert b"ListenBrainz imports are temporarily unavailable." in response.content
    assert ImportRun.objects.filter(user=user).count() == 0
    delay.assert_not_called()


def test_import_create_validation_errors_render_alert(client):
    user = create_user()
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:import_list"),
        {
            "source": "plain_text",
            "plain_text-artist_names": "",
        },
    )

    assert response.status_code == 400
    assert b'role="alert"' in response.content
    assert b"This field is required." in response.content
    assert ImportRun.objects.filter(user=user).count() == 0


def test_import_create_rate_limit_returns_429(client, mocker):
    user = create_user()
    client.force_login(user)
    mocker.patch(
        "releasewatch.views.check_rate_limit",
        return_value=mocker.Mock(allowed=False, retry_after_seconds=30),
    )

    response = client.post(
        reverse("releasewatch:import_list"),
        {
            "source": "plain_text",
            "plain_text-artist_names": "Fugazi",
        },
    )

    assert response.status_code == 429
    assert ImportRun.objects.filter(user=user).count() == 0


def test_import_detail_blocks_cross_user_access(client):
    user = create_user()
    other = create_user("other")
    run = create_run(other)
    client.force_login(user)

    response = client.get(reverse("releasewatch:import_detail", args=[run.id]))

    assert response.status_code == 404


def test_import_detail_shows_current_user_run(client):
    user = create_user()
    run = create_run(user)
    create_candidate(run)
    client.force_login(user)

    response = client.get(reverse("releasewatch:import_detail", args=[run.id]))

    assert response.status_code == 200
    assert b"Unknown Artist" in response.content


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


def test_invalid_import_review_action_redirects_without_changing_candidate(client):
    user = create_user()
    run = create_run(user)
    candidate = create_candidate(run)
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:review_import_candidate", args=[candidate.id]),
        {"action": "bad"},
    )

    assert response.status_code == 302
    candidate.refresh_from_db()
    assert candidate.review_state == ImportCandidate.ReviewState.PENDING


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


def test_reject_import_candidate_marks_candidate_rejected(client):
    user = create_user()
    run = create_run(user)
    candidate = create_candidate(run)
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:review_import_candidate", args=[candidate.id]),
        {"action": "reject"},
    )

    assert response.status_code == 302
    candidate.refresh_from_db()
    assert candidate.review_state == ImportCandidate.ReviewState.REJECTED


def test_review_import_candidate_requires_post(client):
    user = create_user()
    run = create_run(user)
    candidate = create_candidate(run)
    client.force_login(user)

    response = client.get(reverse("releasewatch:review_import_candidate", args=[candidate.id]))

    assert response.status_code == 405


def test_review_import_candidate_rate_limit_returns_429(client, mocker):
    user = create_user()
    run = create_run(user)
    candidate = create_candidate(run)
    client.force_login(user)
    mocker.patch(
        "releasewatch.views.check_rate_limit",
        return_value=mocker.Mock(allowed=False, retry_after_seconds=30),
    )

    response = client.post(
        reverse("releasewatch:review_import_candidate", args=[candidate.id]),
        {"action": "reject"},
    )

    assert response.status_code == 429


def test_import_review_requires_csrf_token():
    user = create_user("csrf-user")
    run = create_run(user)
    candidate = create_candidate(run)
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    response = client.post(
        reverse("releasewatch:review_import_candidate", args=[candidate.id]),
        {"action": "reject"},
    )

    assert response.status_code == 403
