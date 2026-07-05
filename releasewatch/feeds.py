import hashlib
import secrets
from dataclasses import dataclass
from email.utils import format_datetime
from html import escape

from django.http import Http404
from django.urls import reverse
from django.utils import timezone

from releasewatch.models import FeedToken, ReleaseEvent


@dataclass(frozen=True)
class CreatedFeedToken:
    token: str
    record: FeedToken


def create_feed_token(*, user, feed_type: str, name: str = "") -> str:
    created = create_feed_token_record(user=user, feed_type=feed_type, name=name)
    return created.token


def create_feed_token_record(*, user, feed_type: str, name: str = "") -> CreatedFeedToken:
    token = secrets.token_urlsafe(32)
    record = FeedToken.objects.create(
        user=user,
        feed_type=feed_type,
        token_hash=_hash_token(token),
        name=name[:100],
    )
    return CreatedFeedToken(token=token, record=record)


def feed_token_for_request(*, token: str, feed_type: str) -> FeedToken:
    record = (
        FeedToken.objects.select_related("user")
        .filter(token_hash=_hash_token(token), feed_type=feed_type, revoked_at__isnull=True)
        .first()
    )
    if record is None:
        raise Http404("Feed not found.")
    record.last_used_at = timezone.now()
    record.save(update_fields=["last_used_at"])
    return record


def user_release_events(user):
    return (
        ReleaseEvent.objects.select_related("release_group__artist", "release")
        .filter(
            visible=True,
            release_group__artist__follow__user=user,
            release_group__artist__follow__is_ignored=False,
        )
        .order_by("-event_date", "release_group__artist__sort_name", "release_group__title", "id")
        .distinct()
    )


def render_rss_feed(*, request, token_record: FeedToken, events) -> str:
    now = format_datetime(timezone.now())
    title = f"Muspy releases for {token_record.user.get_username()}"
    release_list_url = request.build_absolute_uri(reverse("releasewatch:release_list"))
    items = "\n".join(_rss_item(request=request, event=event) for event in events)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<rss version="2.0">\n'
        "  <channel>\n"
        f"    <title>{escape(title)}</title>\n"
        f"    <link>{escape(release_list_url)}</link>\n"
        "    <description>Followed artist releases from Muspy.</description>\n"
        f"    <lastBuildDate>{escape(now)}</lastBuildDate>\n"
        f"{items}\n"
        "  </channel>\n"
        "</rss>\n"
    )


def render_ical_feed(*, request, events) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Muspy//Release Calendar//EN",
        "CALSCALE:GREGORIAN",
    ]
    for event in events:
        lines.extend(_ical_event(request=request, event=event))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _rss_item(*, request, event: ReleaseEvent) -> str:
    title = _event_title(event)
    link = request.build_absolute_uri(reverse("releasewatch:release_detail", args=[event.id]))
    event_date = event.event_date.isoformat() if event.event_date else ""
    return (
        "    <item>\n"
        f"      <title>{escape(title)}</title>\n"
        f"      <link>{escape(link)}</link>\n"
        f"      <guid>{escape(link)}</guid>\n"
        f"      <description>{escape(event_date)}</description>\n"
        "    </item>"
    )


def _ical_event(*, request, event: ReleaseEvent) -> list[str]:
    title = _event_title(event)
    link = request.build_absolute_uri(reverse("releasewatch:release_detail", args=[event.id]))
    date_value = (
        event.event_date.strftime("%Y%m%d")
        if event.event_date
        else timezone.now().strftime("%Y%m%d")
    )
    return [
        "BEGIN:VEVENT",
        f"UID:release-{event.id}@muspy",
        f"DTSTAMP:{timezone.now().strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART;VALUE=DATE:{date_value}",
        f"SUMMARY:{_escape_ical(title)}",
        f"URL:{_escape_ical(link)}",
        "END:VEVENT",
    ]


def _event_title(event: ReleaseEvent) -> str:
    return f"{event.release_group.artist.name} - {event.release_group.title}"


def _escape_ical(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
