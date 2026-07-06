from celery import shared_task
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from releasewatch.imports import (
    mark_import_failed,
    start_lastfm_import,
    start_listenbrainz_import,
    start_plain_text_import,
)
from releasewatch.models import Artist, ImportRun, ProviderAccount, ReleaseEvent, SyncState
from releasewatch.notification_delivery import send_pending_notification_emails
from releasewatch.notifications import fanout_release_event_notifications
from releasewatch.provider_tokens import ProviderTokenError, decrypt_provider_token
from releasewatch.sync import ReleaseSyncError, sync_artist_releases


@shared_task(bind=True, autoretry_for=(TimeoutError,), retry_backoff=True, retry_jitter=True)
def run_import(self, import_run_id: int) -> None:
    run = ImportRun.objects.select_related("user").get(pk=import_run_id)
    if run.status == ImportRun.Status.PENDING_REVIEW:
        return
    if run.source == ImportRun.Source.PLAIN_TEXT:
        text = str(run.raw_payload.get("text", ""))
        imported_run = start_plain_text_import(user=run.user, text=text)
        _replace_import_run_contents(run=run, imported_run=imported_run)
        return
    if run.source == ImportRun.Source.LASTFM:
        imported_run = start_lastfm_import(
            user=run.user,
            username=str(run.raw_payload.get("username", "")),
        )
        _replace_import_run_contents(run=run, imported_run=imported_run)
        return
    if run.source == ImportRun.Source.LISTENBRAINZ:
        token_encrypted = str(run.raw_payload.get("token_encrypted", ""))
        try:
            token = decrypt_provider_token(token_encrypted)
        except (ImproperlyConfigured, ProviderTokenError):
            mark_import_failed(run=run, message="ListenBrainz token could not be read.")
            return
        if not token:
            mark_import_failed(run=run, message="ListenBrainz token is missing.")
            return
        imported_run = start_listenbrainz_import(
            user=run.user,
            username=str(run.raw_payload.get("username", "")),
            token=token,
            persist_token=False,
        )
        _replace_import_run_contents(run=run, imported_run=imported_run)
        return
    mark_import_failed(run=run, message=f"Unsupported import source: {run.source}")


def _replace_import_run_contents(*, run: ImportRun, imported_run: ImportRun) -> None:
    run.candidates.all().delete()
    for candidate in imported_run.candidates.all():
        candidate.import_run = run
        candidate.pk = None
        candidate.save()
    run.status = imported_run.status
    run.error_message = imported_run.error_message
    run.raw_payload = imported_run.raw_payload
    run.save(update_fields=["status", "error_message", "raw_payload", "updated_at"])
    imported_run.delete()


@shared_task(bind=True, autoretry_for=(TimeoutError,), retry_backoff=True, retry_jitter=True)
def import_provider_account(self, provider_account_id: int) -> None:
    account = ProviderAccount.objects.select_related("user").get(pk=provider_account_id)
    if account.status != ProviderAccount.Status.ACTIVE:
        return
    try:
        import_run = _run_provider_import(account)
        if import_run.status == ImportRun.Status.FAILED:
            raise RuntimeError(import_run.error_message or "Provider import failed.")
    except Exception as error:
        _mark_account_failed(account=account, message=str(error))
        return
    account.last_imported_at = timezone.now()
    account.last_error_message = ""
    account.save(update_fields=["last_imported_at", "last_error_message", "updated_at"])


@shared_task
def enqueue_due_provider_imports(batch_size: int = 100) -> int:
    with transaction.atomic():
        accounts = list(
            ProviderAccount.objects.select_for_update(skip_locked=True)
            .filter(status=ProviderAccount.Status.ACTIVE)
            .order_by(F("last_imported_at").asc(nulls_first=True), "id")[:batch_size]
        )
    for account in accounts:
        import_provider_account.delay(account.id)
    return len(accounts)


@shared_task(
    bind=True,
    autoretry_for=(ReleaseSyncError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
)
def sync_artist_releases_task(self, artist_id: int) -> None:
    artist = Artist.objects.get(pk=artist_id)
    if not _artist_release_sync_due(artist):
        return
    result = sync_artist_releases(artist=artist)
    for event_id in result.event_ids:
        fanout_release_notifications.delay(event_id)


@shared_task(bind=True, autoretry_for=(TimeoutError,), retry_backoff=True, retry_jitter=True)
def fanout_release_notifications(self, release_event_id: int) -> None:
    event = ReleaseEvent.objects.select_related("release_group__artist").get(pk=release_event_id)
    fanout_release_event_notifications(release_event=event)


@shared_task(bind=True, autoretry_for=(TimeoutError,), retry_backoff=True, retry_jitter=True)
def send_pending_notification_emails_task(self, batch_size: int = 100) -> None:
    send_pending_notification_emails(batch_size=batch_size)


@shared_task
def enqueue_due_artist_syncs(batch_size: int = 100) -> int:
    artist_ids = _due_artist_ids(batch_size=batch_size)
    for artist_id in artist_ids:
        sync_artist_releases_task.delay(artist_id)
    return len(artist_ids)


def _run_provider_import(account: ProviderAccount) -> ImportRun:
    if account.provider == ProviderAccount.Provider.LASTFM:
        return start_lastfm_import(user=account.user, username=account.external_username)
    if account.provider == ProviderAccount.Provider.LISTENBRAINZ:
        token = decrypt_provider_token(account.token_encrypted)
        if not token:
            raise ProviderTokenError("Provider account token is missing.")
        return start_listenbrainz_import(
            user=account.user,
            username=account.external_username,
            token=token,
            persist_token=False,
        )
    raise ValueError(f"Unsupported provider: {account.provider}")


def _mark_account_failed(*, account: ProviderAccount, message: str) -> None:
    account.status = ProviderAccount.Status.FAILED
    account.last_error_message = message
    account.save(update_fields=["status", "last_error_message", "updated_at"])


def _due_artist_ids(*, batch_size: int) -> list[int]:
    now = timezone.now()
    stale_before = now - timezone.timedelta(hours=settings.RELEASE_SYNC_FRESHNESS_HOURS)
    followed_artists = Artist.objects.filter(follow__is_ignored=False).distinct()
    release_sync_states = SyncState.objects.filter(
        artist_id=OuterRef("pk"),
        sync_type=SyncState.SyncType.RELEASES,
    )

    never_synced = (
        followed_artists.annotate(has_release_sync=Exists(release_sync_states))
        .filter(has_release_sync=False)
        .order_by("id")
        .values_list("id", flat=True)
    )
    retryable_failures = (
        followed_artists.filter(
            sync_states__sync_type=SyncState.SyncType.RELEASES,
            sync_states__status=SyncState.Status.FAILED,
        )
        .filter(Q(sync_states__retry_after__isnull=True) | Q(sync_states__retry_after__lte=now))
        .order_by("sync_states__retry_after", "id")
        .values_list("id", flat=True)
    )
    stale_successes = (
        followed_artists.filter(
            sync_states__sync_type=SyncState.SyncType.RELEASES,
            sync_states__status=SyncState.Status.SUCCEEDED,
        )
        .filter(
            Q(sync_states__last_succeeded_at__isnull=True)
            | Q(sync_states__last_succeeded_at__lt=stale_before)
        )
        .order_by("sync_states__last_succeeded_at", "id")
        .values_list("id", flat=True)
    )
    return _take_unique_ids(
        never_synced,
        retryable_failures,
        stale_successes,
        batch_size=batch_size,
    )


def _take_unique_ids(*querysets, batch_size: int) -> list[int]:
    due_ids: list[int] = []
    seen_ids: set[int] = set()
    for queryset in querysets:
        for artist_id in queryset:
            if artist_id in seen_ids:
                continue
            due_ids.append(artist_id)
            seen_ids.add(artist_id)
            if len(due_ids) >= batch_size:
                return due_ids
    return due_ids


def _artist_release_sync_due(
    artist: Artist,
    *,
    now=None,
    stale_before=None,
) -> bool:
    now = now or timezone.now()
    stale_before = stale_before or now - timezone.timedelta(
        hours=settings.RELEASE_SYNC_FRESHNESS_HOURS
    )
    sync_state = SyncState.objects.filter(
        artist=artist,
        sync_type=SyncState.SyncType.RELEASES,
    ).first()
    if sync_state is None:
        return True
    if sync_state.status == SyncState.Status.FAILED:
        return sync_state.retry_after is None or sync_state.retry_after <= now
    if sync_state.last_succeeded_at is None:
        return True
    return sync_state.last_succeeded_at < stale_before
