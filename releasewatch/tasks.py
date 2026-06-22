from celery import shared_task
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from releasewatch.imports import (
    mark_import_failed,
    start_lastfm_import,
    start_listenbrainz_import,
    start_plain_text_import,
)
from releasewatch.models import ImportRun, ProviderAccount
from releasewatch.provider_tokens import ProviderTokenError, decrypt_provider_token


@shared_task(bind=True, autoretry_for=(TimeoutError,), retry_backoff=True, retry_jitter=True)
def run_import(self, import_run_id: int) -> None:
    run = ImportRun.objects.select_related("user").get(pk=import_run_id)
    if run.status == ImportRun.Status.PENDING_REVIEW:
        return
    if run.source == ImportRun.Source.PLAIN_TEXT:
        text = str(run.raw_payload.get("text", ""))
        imported_run = start_plain_text_import(user=run.user, text=text)
        run.candidates.all().delete()
        for candidate in imported_run.candidates.all():
            candidate.import_run = run
            candidate.pk = None
            candidate.save()
        imported_run.delete()
        run.status = ImportRun.Status.PENDING_REVIEW
        run.error_message = ""
        run.save(update_fields=["status", "error_message", "updated_at"])
        return
    mark_import_failed(run=run, message=f"Unsupported import source: {run.source}")


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
