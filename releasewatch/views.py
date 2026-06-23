from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from releasewatch.forms import ArtistSearchForm, FollowArtistForm
from releasewatch.models import Artist, Follow, ReleaseEvent
from releasewatch.rate_limits import (
    RateLimitUnavailable,
    check_rate_limit,
    rate_limit_unavailable_response,
    rate_limited_response,
)
from releasewatch.tasks import sync_artist_releases_task
from releasewatch.upstreams import MusicBrainzClient, UpstreamError


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
    return render(request, "releasewatch/artist_detail.html", {"artist": artist, "events": events})


def release_detail(request, event_id: int):
    event = get_object_or_404(visible_release_events(), pk=event_id)
    return render(request, "releasewatch/release_detail.html", {"event": event})
