import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from releasewatch.models import Artist, Follow, ImportCandidate, ImportRun, ProviderAccount
from releasewatch.provider_tokens import encrypt_provider_token, redact_provider_secrets
from releasewatch.upstreams.base import ImportedArtist
from releasewatch.upstreams.lastfm import LastFmClient
from releasewatch.upstreams.listenbrainz import ListenBrainzClient

MAX_MODEL_STRING_LENGTH = 255
IDENTIFIER_HASH_LENGTH = 12


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


def start_lastfm_import(
    *,
    user,
    username: str,
    client: LastFmClient | None = None,
) -> ImportRun:
    client = client or LastFmClient()
    run = ImportRun.objects.create(
        user=user,
        source=ImportRun.Source.LASTFM,
        status=ImportRun.Status.STARTED,
        raw_payload={"username": username},
    )
    try:
        imported = client.get_user_top_artists(username, limit=100, page=1)
        apply_imported_artists(run=run, imported_artists=imported)
    except Exception as error:
        mark_import_failed(run=run, message=str(error))
        run.refresh_from_db()
        return run
    run.refresh_from_db()
    return run


def start_listenbrainz_import(
    *,
    user,
    username: str,
    token: str,
    client: ListenBrainzClient | None = None,
    persist_token: bool = False,
) -> ImportRun:
    client = client or ListenBrainzClient()
    if persist_token:
        ProviderAccount.objects.update_or_create(
            user=user,
            provider=ProviderAccount.Provider.LISTENBRAINZ,
            external_username=username,
            defaults={
                "token_encrypted": encrypt_provider_token(token),
                "status": ProviderAccount.Status.ACTIVE,
                "last_error_message": "",
            },
        )
    run = ImportRun.objects.create(
        user=user,
        source=ImportRun.Source.LISTENBRAINZ,
        status=ImportRun.Status.STARTED,
        raw_payload={"username": username},
    )
    try:
        imported = client.get_user_artists(username, token, count=100, offset=0)
        apply_imported_artists(run=run, imported_artists=imported)
    except Exception as error:
        run.raw_payload = redact_provider_secrets(run.raw_payload, secret_values=[token])
        run.save(update_fields=["raw_payload", "updated_at"])
        mark_import_failed(run=run, message=str(error).replace(token, "[redacted]"))
        run.refresh_from_db()
        return run
    run.refresh_from_db()
    return run


def apply_imported_artists(
    *,
    run: ImportRun,
    imported_artists: Iterable[ImportedArtist],
    name_matcher: Callable[[ImportedArtist], Artist | None] | None = None,
) -> ImportResult:
    created_count = 0
    updated_count = 0
    with transaction.atomic():
        locked_run = ImportRun.objects.select_for_update().get(pk=run.pk)
        for imported_artist in imported_artists:
            source_identifier = _source_identifier_for_imported(imported_artist)
            artist = _artist_for_imported(imported_artist)
            if artist is None and name_matcher is not None:
                artist = name_matcher(imported_artist)
            _, created = ImportCandidate.objects.update_or_create(
                import_run=locked_run,
                source_identifier=source_identifier,
                defaults={
                    "artist": artist,
                    "source_name": _clamp_model_string(imported_artist.source_name),
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
    with transaction.atomic():
        locked_candidate = ImportCandidate.objects.select_for_update().get(pk=candidate.pk)
        if locked_candidate.artist is None:
            raise ValueError("Import candidate has no matched artist.")
        follow, _ = Follow.objects.update_or_create(
            user=user,
            artist=locked_candidate.artist,
            defaults={"is_ignored": False},
        )
        locked_candidate.review_state = ImportCandidate.ReviewState.ACCEPTED
        locked_candidate.reviewed_at = timezone.now()
        locked_candidate.save(update_fields=["review_state", "reviewed_at"])
    candidate.refresh_from_db()
    return follow


def ignore_import_candidate(*, candidate: ImportCandidate, user) -> Follow | None:
    _ensure_candidate_owner(candidate=candidate, user=user)
    follow = None
    with transaction.atomic():
        locked_candidate = ImportCandidate.objects.select_for_update().get(pk=candidate.pk)
        if locked_candidate.artist is not None:
            follow, _ = Follow.objects.update_or_create(
                user=user,
                artist=locked_candidate.artist,
                defaults={"is_ignored": True},
            )
        locked_candidate.review_state = ImportCandidate.ReviewState.IGNORED
        locked_candidate.reviewed_at = timezone.now()
        locked_candidate.save(update_fields=["review_state", "reviewed_at"])
    candidate.refresh_from_db()
    return follow


def reject_import_candidate(*, candidate: ImportCandidate, user) -> None:
    _ensure_candidate_owner(candidate=candidate, user=user)
    with transaction.atomic():
        locked_candidate = ImportCandidate.objects.select_for_update().get(pk=candidate.pk)
        locked_candidate.review_state = ImportCandidate.ReviewState.REJECTED
        locked_candidate.reviewed_at = timezone.now()
        locked_candidate.save(update_fields=["review_state", "reviewed_at"])
    candidate.refresh_from_db()


def _artist_for_imported(imported_artist: ImportedArtist) -> Artist | None:
    if not isinstance(imported_artist.mbid, str) or not imported_artist.mbid:
        return None
    try:
        mbid = UUID(imported_artist.mbid)
    except ValueError:
        return None
    artist, _ = Artist.objects.update_or_create(
        mbid=mbid,
        defaults={
            "name": _clamp_model_string(imported_artist.source_name),
            "raw_payload": imported_artist.raw_payload,
        },
    )
    return artist


def _source_identifier_for_imported(imported_artist: ImportedArtist) -> str:
    if imported_artist.source_identifier:
        return _bounded_identifier(str(imported_artist.source_identifier))
    return _bounded_identifier(f"name:{imported_artist.source_name.casefold()}")


def _bounded_identifier(value: str, *, max_length: int = MAX_MODEL_STRING_LENGTH) -> str:
    value = str(value)
    if len(value) <= max_length:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:IDENTIFIER_HASH_LENGTH]
    prefix_length = max_length - IDENTIFIER_HASH_LENGTH - 1
    return f"{value[:prefix_length]}:{digest}"


def _clamp_model_string(value: str, *, max_length: int = MAX_MODEL_STRING_LENGTH) -> str:
    return str(value)[:max_length]


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
