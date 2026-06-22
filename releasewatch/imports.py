from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from releasewatch.models import Artist, Follow, ImportCandidate, ImportRun
from releasewatch.upstreams.base import ImportedArtist


@dataclass(frozen=True)
class ImportResult:
    run: ImportRun
    created_count: int
    updated_count: int


def start_plain_text_import(*, user, text: str) -> ImportRun:
    names = _plain_text_names(text)
    run = ImportRun.objects.create(
        user=user,
        source=ImportRun.Source.PLAIN_TEXT,
        status=ImportRun.Status.STARTED,
        raw_payload={"line_count": len(text.splitlines())},
    )
    imported = [
        ImportedArtist(
            source_name=name,
            source_identifier=f"plain:{name.casefold()}",
            mbid="",
            raw_payload={"name": name},
        )
        for name in names
    ]
    apply_imported_artists(run=run, imported_artists=imported)
    return run


def apply_imported_artists(
    *,
    run: ImportRun,
    imported_artists: Iterable[ImportedArtist],
) -> ImportResult:
    created_count = 0
    updated_count = 0
    with transaction.atomic():
        locked_run = ImportRun.objects.select_for_update().get(pk=run.pk)
        for imported_artist in imported_artists:
            artist = _artist_for_imported(imported_artist)
            _, created = ImportCandidate.objects.update_or_create(
                import_run=locked_run,
                source_identifier=imported_artist.source_identifier,
                defaults={
                    "artist": artist,
                    "source_name": imported_artist.source_name,
                    "raw_payload": imported_artist.raw_payload,
                },
            )
            if created:
                created_count += 1
            else:
                updated_count += 1
        locked_run.status = ImportRun.Status.PENDING_REVIEW
        locked_run.error_message = ""
        locked_run.save(update_fields=["status", "error_message", "updated_at"])
    run.refresh_from_db()
    return ImportResult(run=run, created_count=created_count, updated_count=updated_count)


def mark_import_failed(*, run: ImportRun, message: str) -> None:
    run.status = ImportRun.Status.FAILED
    run.error_message = message
    run.save(update_fields=["status", "error_message", "updated_at"])


def accept_import_candidate(*, candidate: ImportCandidate, user) -> Follow:
    _ensure_candidate_owner(candidate=candidate, user=user)
    if candidate.artist is None:
        raise ValueError("Import candidate has no matched artist.")
    follow, _ = Follow.objects.update_or_create(
        user=user,
        artist=candidate.artist,
        defaults={"is_ignored": False},
    )
    candidate.review_state = ImportCandidate.ReviewState.ACCEPTED
    candidate.reviewed_at = timezone.now()
    candidate.save(update_fields=["review_state", "reviewed_at"])
    return follow


def ignore_import_candidate(*, candidate: ImportCandidate, user) -> Follow | None:
    _ensure_candidate_owner(candidate=candidate, user=user)
    follow = None
    if candidate.artist is not None:
        follow, _ = Follow.objects.update_or_create(
            user=user,
            artist=candidate.artist,
            defaults={"is_ignored": True},
        )
    candidate.review_state = ImportCandidate.ReviewState.IGNORED
    candidate.reviewed_at = timezone.now()
    candidate.save(update_fields=["review_state", "reviewed_at"])
    return follow


def _artist_for_imported(imported_artist: ImportedArtist) -> Artist | None:
    if not imported_artist.mbid:
        return None
    artist, _ = Artist.objects.update_or_create(
        mbid=UUID(imported_artist.mbid),
        defaults={
            "name": imported_artist.source_name,
            "raw_payload": imported_artist.raw_payload,
        },
    )
    return artist


def _plain_text_names(text: str) -> list[str]:
    seen = set()
    names = []
    for line in text.splitlines():
        name = " ".join(line.strip().split())
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _ensure_candidate_owner(*, candidate: ImportCandidate, user) -> None:
    if candidate.import_run.user_id != user.id:
        raise PermissionError("Import candidate does not belong to user.")
