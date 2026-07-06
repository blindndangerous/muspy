from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from releasewatch.api import serialize_artist_detail, serialize_release_event
from releasewatch.feeds import (
    create_feed_token_record,
    feed_token_for_request,
    render_ical_feed,
    render_rss_feed,
    user_release_events,
)
from releasewatch.forms import (
    AccountDeleteForm,
    AccountPasswordChangeForm,
    AccountSettingsForm,
    ArtistSearchForm,
    FeedTokenForm,
    FollowArtistForm,
    ImportCandidateReviewForm,
    InviteSignupForm,
    LastFmImportForm,
    ListenBrainzImportForm,
    NotificationPreferenceForm,
    PlainTextImportForm,
    RemoveFollowForm,
)
from releasewatch.images import artist_image_url, release_cover_art_url
from releasewatch.imports import (
    accept_import_candidate,
    ignore_import_candidate,
    reject_import_candidate,
)
from releasewatch.models import (
    Artist,
    FeedToken,
    Follow,
    ImportCandidate,
    ImportRun,
    Invite,
    NotificationPreference,
    ReleaseEvent,
    UserProfile,
)
from releasewatch.notification_delivery import EmailDeliveryError, send_email_verification_email
from releasewatch.notifications import (
    InvalidEmailLinkToken,
    user_for_email_verification_token,
    user_for_unsubscribe_token,
)
from releasewatch.provider_tokens import encrypt_provider_token
from releasewatch.rate_limits import (
    RateLimitUnavailable,
    check_rate_limit,
    rate_limit_unavailable_response,
    rate_limited_response,
)
from releasewatch.tasks import run_import as run_import_task
from releasewatch.tasks import sync_artist_releases_task
from releasewatch.upstreams import MusicBrainzClient, UpstreamError

PUBLIC_API_EVENT_LIMIT = 100


def health(request):
    return JsonResponse({"status": "ok"})


def visible_release_events():
    return (
        ReleaseEvent.objects.select_related("release_group__artist", "release")
        .filter(visible=True)
        .order_by("event_date", "release_group__artist__sort_name", "release_group__title", "id")
    )


def _guard_rate_limit(request, *, scope: str, rate: tuple[int, int], identity="user_or_ip"):
    limit, window_seconds = rate
    try:
        result = check_rate_limit(
            request,
            scope=scope,
            limit=limit,
            window_seconds=window_seconds,
            identity=identity,
        )
    except RateLimitUnavailable:
        return rate_limit_unavailable_response(request)
    if not result.allowed:
        return rate_limited_response(request, retry_after_seconds=result.retry_after_seconds)
    return None


def _artist_from_upstream(upstream_artist):
    artist, _ = Artist.objects.update_or_create(
        mbid=upstream_artist.mbid,
        defaults={
            "name": upstream_artist.name[:255],
            "sort_name": upstream_artist.sort_name[:255],
            "disambiguation": upstream_artist.disambiguation[:255],
            "artist_type": upstream_artist.artist_type[:64],
            "country": upstream_artist.country[:2],
            "raw_payload": upstream_artist.raw_payload,
        },
    )
    return artist


def home(request):
    events = visible_release_events()
    today = timezone.localdate()
    return render(
        request,
        "releasewatch/home.html",
        {
            "recent_events": events.filter(event_date__lt=today).order_by(
                "-event_date",
                "release_group__artist__sort_name",
                "release_group__title",
                "id",
            )[:10],
            "upcoming_events": events.filter(event_date__gte=today)[:10],
        },
    )


def release_list(request):
    return render(
        request,
        "releasewatch/release_list.html",
        {"events": visible_release_events()[:100]},
    )


def about(request):
    return render(request, "releasewatch/about.html")


def faq(request):
    return render(request, "releasewatch/faq.html")


def contact(request):
    return render(request, "releasewatch/contact.html")


def sitemap(request):
    route_names = [
        "releasewatch:home",
        "releasewatch:about",
        "releasewatch:faq",
        "releasewatch:contact",
        "releasewatch:release_list",
        "releasewatch:api_v1_release_list",
    ]
    urls = [request.build_absolute_uri(reverse(route_name)) for route_name in route_names]
    return render(
        request,
        "releasewatch/sitemap.xml",
        {"urls": urls},
        content_type="application/xml; charset=utf-8",
    )


@require_GET
def api_v1_release_list(request):
    events = visible_release_events()[:PUBLIC_API_EVENT_LIMIT]
    return JsonResponse(
        {"releases": [serialize_release_event(event) for event in events]},
    )


@require_GET
def api_v1_artist_detail(request, artist_mbid):
    artist = get_object_or_404(
        Artist.objects.filter(release_groups__events__visible=True).distinct(),
        mbid=artist_mbid,
    )
    events = visible_release_events().filter(release_group__artist=artist)[
        :PUBLIC_API_EVENT_LIMIT
    ]
    return JsonResponse(serialize_artist_detail(artist, events))


def signup_with_invite(request, code: str):
    invite = get_object_or_404(Invite, code=code)
    if not invite.can_be_used:
        raise Http404("Invite not available.")

    if request.method == "POST":
        form = InviteSignupForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                locked_invite = get_object_or_404(Invite.objects.select_for_update(), code=code)
                if not locked_invite.can_be_used:
                    raise Http404("Invite not available.")
                user = form.save()
                locked_invite.uses += 1
                locked_invite.save(update_fields=["uses"])
            login(request, user)
            messages.success(request, "Account created.")
            return redirect("releasewatch:dashboard")
    else:
        form = InviteSignupForm()

    return render(request, "registration/signup.html", {"form": form, "invite": invite})


@login_required
def dashboard(request):
    follows = (
        Follow.objects.select_related("artist")
        .filter(user=request.user, is_ignored=False)
        .order_by("artist__sort_name", "artist__name")
    )
    events = visible_release_events().filter(
        release_group__artist__follow__user=request.user,
        release_group__artist__follow__is_ignored=False,
    ).order_by(
        "-event_date",
        "release_group__artist__sort_name",
        "release_group__title",
        "id",
    )[:20]
    return render(request, "releasewatch/dashboard.html", {"follows": follows, "events": events})


@login_required
def follow_list(request):
    follows = (
        Follow.objects.select_related("artist")
        .filter(user=request.user)
        .order_by("is_ignored", "artist__sort_name", "artist__name")
    )
    return render(request, "releasewatch/follow_list.html", {"follows": follows})


@login_required
def remove_follow(request, follow_id: int):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    follow = get_object_or_404(
        Follow.objects.select_related("artist"),
        pk=follow_id,
        user=request.user,
    )
    form = RemoveFollowForm(request.POST)
    if form.is_valid():
        artist_name = follow.artist.name
        was_ignored = follow.is_ignored
        follow.delete()
        if was_ignored:
            messages.success(request, f"Removed {artist_name}.")
        else:
            messages.success(request, f"Unfollowed {artist_name}.")
    return redirect("releasewatch:follow_list")


@login_required
def import_list(request):
    runs = ImportRun.objects.filter(user=request.user).order_by("-created_at", "-id")
    forms = _import_start_forms()
    import_source_error = ""

    if request.method == "POST":
        limited_response = _guard_rate_limit(
            request,
            scope="import-create",
            rate=settings.RATE_LIMIT_IMPORT_CREATE,
        )
        if limited_response is not None:
            return limited_response

        source = request.POST.get("source", "")
        forms = _import_start_forms(data=request.POST, source=source)
        form = forms.get(source)
        if form is None:
            import_source_error = "Choose a valid import source."
        elif form.is_valid():
            try:
                run = _create_import_run_from_form(
                    user=request.user,
                    source=source,
                    form=form,
                )
            except ImproperlyConfigured:
                form.add_error("token", "ListenBrainz imports are temporarily unavailable.")
                return render(
                    request,
                    "releasewatch/import_list.html",
                    _import_list_context(runs=runs, forms=forms),
                    status=503,
                )
            else:
                return redirect("releasewatch:import_detail", run_id=run.id)

        return render(
            request,
            "releasewatch/import_list.html",
            _import_list_context(
                runs=runs,
                forms=forms,
                import_source_error=import_source_error,
            ),
            status=400,
        )

    return render(
        request,
        "releasewatch/import_list.html",
        _import_list_context(runs=runs, forms=forms),
    )


def _import_start_forms(*, data=None, source=""):
    return {
        ImportRun.Source.PLAIN_TEXT: PlainTextImportForm(
            data if source == ImportRun.Source.PLAIN_TEXT else None,
            prefix="plain_text",
        ),
        ImportRun.Source.LASTFM: LastFmImportForm(
            data if source == ImportRun.Source.LASTFM else None,
            prefix="lastfm",
        ),
        ImportRun.Source.LISTENBRAINZ: ListenBrainzImportForm(
            data if source == ImportRun.Source.LISTENBRAINZ else None,
            prefix="listenbrainz",
        ),
    }


def _import_list_context(*, runs, forms, import_source_error=""):
    return {
        "runs": runs,
        "plain_text_form": forms[ImportRun.Source.PLAIN_TEXT],
        "lastfm_form": forms[ImportRun.Source.LASTFM],
        "listenbrainz_form": forms[ImportRun.Source.LISTENBRAINZ],
        "import_source_error": import_source_error,
    }


def _create_import_run_from_form(*, user, source, form):
    if source == ImportRun.Source.PLAIN_TEXT:
        raw_payload = {"text": form.cleaned_data["artist_names"]}
    elif source == ImportRun.Source.LISTENBRAINZ:
        raw_payload = {"username": form.cleaned_data["username"]}
        raw_payload["token_encrypted"] = encrypt_provider_token(form.cleaned_data["token"])
    else:
        raw_payload = {"username": form.cleaned_data["username"]}

    run = ImportRun.objects.create(
        user=user,
        source=source,
        status=ImportRun.Status.STARTED,
        raw_payload=raw_payload,
    )
    run_import_task.delay(run.id)
    return run


@login_required
def import_detail(request, run_id: int):
    run = get_object_or_404(
        ImportRun.objects.prefetch_related("candidates__artist"),
        pk=run_id,
        user=request.user,
    )
    return render(request, "releasewatch/import_detail.html", {"run": run})


@login_required
def notification_settings(request):
    preference, _ = NotificationPreference.objects.get_or_create(user=request.user)
    if request.method == "POST":
        limited_response = _guard_rate_limit(
            request,
            scope="notification-settings",
            rate=settings.RATE_LIMIT_NOTIFICATION_SETTINGS,
        )
        if limited_response is not None:
            return limited_response
        form = NotificationPreferenceForm(request.POST, instance=preference)
        if form.is_valid():
            form.save()
            messages.success(request, "Notification settings saved.")
            return redirect("releasewatch:notification_settings")
    else:
        form = NotificationPreferenceForm(instance=preference)
    return render(request, "releasewatch/notification_settings.html", {"form": form})


@login_required
def account_settings(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    account_form = AccountSettingsForm(user=request.user, profile=profile)
    password_form = AccountPasswordChangeForm(user=request.user)

    if request.method == "POST":
        if "password-submit" in request.POST:
            limited_response = _guard_rate_limit(
                request,
                scope="account-password",
                rate=settings.RATE_LIMIT_ACCOUNT_PASSWORD,
            )
            if limited_response is not None:
                return limited_response
            password_form = AccountPasswordChangeForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Password changed.")
                return redirect("releasewatch:account_settings")
        else:
            account_form = AccountSettingsForm(
                request.POST,
                user=request.user,
                profile=profile,
            )
            if account_form.is_valid():
                account_form.save()
                messages.success(request, "Account settings saved.")
                return redirect("releasewatch:account_settings")

    return render(
        request,
        "releasewatch/account_settings.html",
        {"account_form": account_form, "password_form": password_form, "profile": profile},
    )


@login_required
@require_POST
def resend_email_verification(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if profile.email_verified:
        messages.info(request, "Email address is already verified.")
        return redirect("releasewatch:account_settings")

    limited_response = _guard_rate_limit(
        request,
        scope="email-verification-resend",
        rate=getattr(settings, "RATE_LIMIT_EMAIL_VERIFICATION_RESEND", (3, 3600)),
    )
    if limited_response is not None:
        return limited_response

    try:
        send_email_verification_email(user=request.user)
    except EmailDeliveryError:
        messages.error(request, "We could not send verification email right now.")
    else:
        messages.success(request, "Verification email sent.")
    return redirect("releasewatch:account_settings")


@login_required
def account_delete(request):
    if request.method == "POST":
        form = AccountDeleteForm(request.POST)
        if form.is_valid():
            user = request.user
            user.delete()
            logout(request)
            messages.success(request, "Your account has been deleted.")
            return redirect("releasewatch:home")
    else:
        form = AccountDeleteForm()

    return render(request, "releasewatch/account_delete.html", {"form": form})


@login_required
def feed_settings(request):
    new_feed_url = ""
    if request.method == "POST":
        form = FeedTokenForm(request.POST)
        if form.is_valid():
            created = create_feed_token_record(
                user=request.user,
                feed_type=form.cleaned_data["feed_type"],
                name=form.cleaned_data["name"],
            )
            route_name = (
                "releasewatch:rss_feed"
                if created.record.feed_type == FeedToken.FeedType.RSS
                else "releasewatch:ical_feed"
            )
            new_feed_url = request.build_absolute_uri(reverse(route_name, args=[created.token]))
            messages.success(request, "Feed token created. Copy the new URL now.")
            form = FeedTokenForm()
    else:
        form = FeedTokenForm()
    tokens = FeedToken.objects.filter(user=request.user).order_by("revoked_at", "-created_at")
    return render(
        request,
        "releasewatch/feed_settings.html",
        {"form": form, "tokens": tokens, "new_feed_url": new_feed_url},
    )


@login_required
def revoke_feed_token(request, token_id: int):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    token = get_object_or_404(FeedToken, pk=token_id, user=request.user)
    if token.revoked_at is None:
        token.revoked_at = timezone.now()
        token.save(update_fields=["revoked_at"])
        messages.success(request, "Feed token revoked.")
    return redirect("releasewatch:feed_settings")


def email_unsubscribe(request, token: str):
    try:
        user = user_for_unsubscribe_token(token)
    except InvalidEmailLinkToken:
        return render(request, "releasewatch/email_link_invalid.html", status=404)

    if request.method == "GET":
        return render(request, "releasewatch/email_unsubscribe_confirm.html")
    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])

    preference, _ = NotificationPreference.objects.get_or_create(user=user)
    if preference.email_enabled:
        preference.email_enabled = False
        preference.save(update_fields=["email_enabled"])
    return render(request, "releasewatch/email_unsubscribed.html")


def verify_email(request, token: str):
    try:
        user = user_for_email_verification_token(token)
    except InvalidEmailLinkToken:
        return render(request, "releasewatch/email_link_invalid.html", status=404)

    profile, _ = UserProfile.objects.get_or_create(user=user)
    if profile.email_verified_at is None:
        profile.email_verified_at = timezone.now()
        profile.save(update_fields=["email_verified_at"])
    return render(request, "releasewatch/email_verified.html")


def rss_feed(request, token: str):
    token_record = feed_token_for_request(token=token, feed_type=FeedToken.FeedType.RSS)
    content = render_rss_feed(
        request=request,
        token_record=token_record,
        events=user_release_events(token_record.user)[:100],
    )
    return HttpResponse(content, content_type="application/rss+xml; charset=utf-8")


def ical_feed(request, token: str):
    token_record = feed_token_for_request(token=token, feed_type=FeedToken.FeedType.ICAL)
    content = render_ical_feed(request=request, events=user_release_events(token_record.user)[:500])
    return HttpResponse(content, content_type="text/calendar; charset=utf-8")


@login_required
def review_import_candidate(request, candidate_id: int):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    limited_response = _guard_rate_limit(
        request,
        scope="import-review",
        rate=settings.RATE_LIMIT_IMPORT_REVIEW,
    )
    if limited_response is not None:
        return limited_response
    candidate = get_object_or_404(
        ImportCandidate.objects.select_related("import_run", "artist"),
        pk=candidate_id,
        import_run__user=request.user,
    )
    form = ImportCandidateReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choose a review action.")
        return redirect("releasewatch:import_detail", run_id=candidate.import_run_id)
    action = form.cleaned_data["action"]
    if action == "accept":
        if candidate.artist_id is None:
            messages.error(request, "Choose ignore or reject for candidates without a match.")
            return redirect("releasewatch:import_detail", run_id=candidate.import_run_id)
        follow = accept_import_candidate(candidate=candidate, user=request.user)
        sync_artist_releases_task.delay(follow.artist_id)
        messages.success(request, f"Accepted {candidate.source_name}.")
    elif action == "ignore":
        ignore_import_candidate(candidate=candidate, user=request.user)
        messages.success(request, f"Ignored {candidate.source_name}.")
    else:
        reject_import_candidate(candidate=candidate, user=request.user)
        messages.success(request, f"Rejected {candidate.source_name}.")
    return redirect("releasewatch:import_detail", run_id=candidate.import_run_id)


@login_required
def artist_search(request):
    form = ArtistSearchForm(request.GET or None)
    results = []
    if form.is_valid():
        limited_response = _guard_rate_limit(
            request,
            scope="artist-search",
            rate=settings.RATE_LIMIT_ARTIST_SEARCH_AUTHENTICATED,
        )
        if limited_response is not None:
            return limited_response
        try:
            with MusicBrainzClient() as client:
                results = client.search_artists(form.cleaned_data["q"], limit=10, offset=0)
        except UpstreamError:
            form.add_error(None, "Artist search is temporarily unavailable.")
            return render(
                request,
                "releasewatch/artist_search.html",
                {"form": form, "results": results},
                status=503,
            )
    return render(request, "releasewatch/artist_search.html", {"form": form, "results": results})


@login_required
def follow_artist(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    limited_response = _guard_rate_limit(
        request,
        scope="follow-mutation",
        rate=settings.RATE_LIMIT_FOLLOW_MUTATION,
    )
    if limited_response is not None:
        return limited_response
    form = FollowArtistForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "releasewatch/artist_search.html",
            {"form": ArtistSearchForm(), "follow_form": form},
            status=400,
        )
    try:
        with MusicBrainzClient() as client:
            upstream_artist = client.lookup_artist(str(form.cleaned_data["mbid"]))
    except UpstreamError:
        form.add_error(None, "Artist follow is temporarily unavailable.")
        return render(
            request,
            "releasewatch/artist_search.html",
            {"form": ArtistSearchForm(), "follow_form": form},
            status=503,
        )
    artist = _artist_from_upstream(upstream_artist)
    Follow.objects.update_or_create(
        user=request.user,
        artist=artist,
        defaults={"is_ignored": False},
    )
    sync_artist_releases_task.delay(artist.id)
    messages.success(request, f"Following {artist.name}.")
    return redirect("releasewatch:follow_list")


def artist_detail(request, artist_id: int):
    artist = get_object_or_404(
        Artist.objects.filter(release_groups__events__visible=True).distinct(),
        pk=artist_id,
    )
    events = visible_release_events().filter(release_group__artist=artist)
    image_url = artist_image_url(artist)
    return render(
        request,
        "releasewatch/artist_detail.html",
        {
            "artist": artist,
            "events": events,
            "artist_image": {
                "url": image_url,
                "alt": f"Artist image for {artist.name}",
            }
            if image_url
            else None,
        },
    )


def release_detail(request, event_id: int):
    event = get_object_or_404(visible_release_events(), pk=event_id)
    cover_art_url = release_cover_art_url(event)
    return render(
        request,
        "releasewatch/release_detail.html",
        {
            "event": event,
            "cover_art": {
                "url": cover_art_url,
                "alt": (
                    f"Cover art for {event.release_group.title} "
                    f"by {event.release_group.artist.name}"
                ),
            }
            if cover_art_url
            else None,
        },
    )
