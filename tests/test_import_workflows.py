from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from releasewatch.imports import (
    accept_import_candidate,
    apply_imported_artists,
    ignore_import_candidate,
    reject_import_candidate,
    start_plain_text_import,
)
from releasewatch.models import Artist, Follow, ImportCandidate, ImportRun
from releasewatch.upstreams.base import ImportedArtist


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


@pytest.mark.django_db
def test_reject_import_candidate_marks_candidate_without_follow():
    user = create_user()
    artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    run = ImportRun.objects.create(user=user, source=ImportRun.Source.PLAIN_TEXT)
    candidate = ImportCandidate.objects.create(
        import_run=run,
        artist=artist,
        source_name="Fugazi",
    )

    reject_import_candidate(candidate=candidate, user=user)

    assert Follow.objects.filter(user=user, artist=artist).count() == 0
    candidate.refresh_from_db()
    assert candidate.review_state == ImportCandidate.ReviewState.REJECTED


@pytest.mark.django_db
def test_imported_artists_without_source_identifiers_use_name_fallbacks():
    user = create_user()
    run = ImportRun.objects.create(user=user, source=ImportRun.Source.LASTFM)

    apply_imported_artists(
        run=run,
        imported_artists=[
            ImportedArtist("Fugazi", "", "", {"name": "Fugazi"}),
            ImportedArtist("Unwound", "", "", {"name": "Unwound"}),
        ],
    )

    assert list(run.candidates.order_by("source_name").values_list("source_name", flat=True)) == [
        "Fugazi",
        "Unwound",
    ]


@pytest.mark.django_db
def test_imported_artist_with_invalid_mbid_stays_pending_without_aborting_run():
    user = create_user()
    run = ImportRun.objects.create(user=user, source=ImportRun.Source.LASTFM)

    apply_imported_artists(
        run=run,
        imported_artists=[
            ImportedArtist("Broken MBID", "lastfm:broken", "not-a-uuid", {"name": "Broken MBID"})
        ],
    )

    run.refresh_from_db()
    candidate = run.candidates.get()
    assert run.status == ImportRun.Status.PENDING_REVIEW
    assert candidate.artist is None
    assert candidate.source_name == "Broken MBID"


@pytest.mark.django_db
def test_imported_artist_without_mbid_uses_high_confidence_name_matcher():
    user = create_user()
    matched_artist = Artist.objects.create(mbid=uuid4(), name="Fugazi")
    run = ImportRun.objects.create(user=user, source=ImportRun.Source.LASTFM)

    apply_imported_artists(
        run=run,
        imported_artists=[ImportedArtist("Fugazi", "", "", {"name": "Fugazi"})],
        name_matcher=lambda imported_artist: matched_artist,
    )

    assert run.candidates.get().artist == matched_artist


@pytest.mark.django_db
def test_imported_artist_long_fields_are_clamped_to_model_limits():
    user = create_user()
    run = ImportRun.objects.create(user=user, source=ImportRun.Source.LASTFM)

    apply_imported_artists(
        run=run,
        imported_artists=[
            ImportedArtist(
                "Long " + ("Artist" * 100),
                "provider:" + ("identifier" * 100),
                "",
                {"name": "long"},
            )
        ],
    )

    candidate = run.candidates.get()
    assert len(candidate.source_name) == 255
    assert len(candidate.source_identifier) == 255


@pytest.mark.django_db
def test_imported_artist_with_valid_mbid_clamps_artist_name_to_model_limit():
    user = create_user()
    run = ImportRun.objects.create(user=user, source=ImportRun.Source.LASTFM)
    mbid = uuid4()

    apply_imported_artists(
        run=run,
        imported_artists=[
            ImportedArtist(
                "Long " + ("Artist" * 100),
                "lastfm:long",
                str(mbid),
                {"name": "long"},
            )
        ],
    )

    artist = Artist.objects.get(mbid=mbid)
    assert len(artist.name) == 255


@pytest.mark.django_db
def test_long_source_identifiers_with_same_prefix_stay_distinct():
    user = create_user()
    run = ImportRun.objects.create(user=user, source=ImportRun.Source.LASTFM)
    shared_prefix = "provider:" + ("same-prefix" * 30)

    apply_imported_artists(
        run=run,
        imported_artists=[
            ImportedArtist("One", f"{shared_prefix}:one", "", {"name": "One"}),
            ImportedArtist("Two", f"{shared_prefix}:two", "", {"name": "Two"}),
        ],
    )

    identifiers = list(
        run.candidates.order_by("source_name").values_list("source_identifier", flat=True)
    )
    assert len(identifiers) == 2
    assert len(set(identifiers)) == 2
    assert all(len(identifier) == 255 for identifier in identifiers)


@pytest.mark.django_db
def test_imported_artist_with_non_string_mbid_stays_pending_without_aborting_run():
    user = create_user()
    run = ImportRun.objects.create(user=user, source=ImportRun.Source.LASTFM)

    apply_imported_artists(
        run=run,
        imported_artists=[
            ImportedArtist("Broken MBID", "lastfm:broken", ["not-a-uuid"], {"name": "Broken MBID"})
        ],
    )

    run.refresh_from_db()
    assert run.status == ImportRun.Status.PENDING_REVIEW
    assert run.candidates.get().artist is None
