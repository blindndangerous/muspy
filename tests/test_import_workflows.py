from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from releasewatch.imports import (
    accept_import_candidate,
    ignore_import_candidate,
    start_plain_text_import,
)
from releasewatch.models import Artist, Follow, ImportCandidate, ImportRun


def create_user(username="import-user"):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        password=None,
    )


@pytest.mark.django_db
def test_plain_text_import_creates_candidates_without_duplicates():
    user = create_user()

    run = start_plain_text_import(user=user, text="Fugazi\n\nFugazi\nUnwound")

    assert run.source == ImportRun.Source.PLAIN_TEXT
    assert run.status == ImportRun.Status.PENDING_REVIEW
    assert list(run.candidates.order_by("source_name").values_list("source_name", flat=True)) == [
        "Fugazi",
        "Unwound",
    ]


@pytest.mark.django_db
def test_accept_import_candidate_creates_follow_once():
    user = create_user()
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    run = ImportRun.objects.create(user=user, source=ImportRun.Source.PLAIN_TEXT)
    candidate = ImportCandidate.objects.create(
        import_run=run,
        artist=artist,
        source_name="Fugazi",
    )

    accept_import_candidate(candidate=candidate, user=user)
    accept_import_candidate(candidate=candidate, user=user)

    assert Follow.objects.filter(user=user, artist=artist, is_ignored=False).count() == 1
    candidate.refresh_from_db()
    assert candidate.review_state == ImportCandidate.ReviewState.ACCEPTED


@pytest.mark.django_db
def test_ignore_import_candidate_marks_candidate_and_follow_ignored():
    user = create_user()
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    run = ImportRun.objects.create(user=user, source=ImportRun.Source.PLAIN_TEXT)
    candidate = ImportCandidate.objects.create(
        import_run=run,
        artist=artist,
        source_name="Fugazi",
    )

    ignore_import_candidate(candidate=candidate, user=user)

    assert Follow.objects.get(user=user, artist=artist).is_ignored is True
    candidate.refresh_from_db()
    assert candidate.review_state == ImportCandidate.ReviewState.IGNORED
