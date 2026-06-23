from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from releasewatch.models import Artist, Follow, ReleaseEvent


def health(request):
    return JsonResponse({"status": "ok"})


def visible_release_events():
    return (
        ReleaseEvent.objects.select_related("release_group__artist", "release")
        .filter(visible=True)
        .order_by("event_date", "release_group__artist__sort_name", "release_group__title", "id")
    )


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
