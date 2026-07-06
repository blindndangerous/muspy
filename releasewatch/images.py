from typing import Any
from urllib.parse import urlparse

COVER_ART_ARCHIVE_BASE_URL = "https://coverartarchive.org"
TRUSTED_IMAGE_HOSTS = (
    "archive.org",
    "coverartarchive.org",
    "wikimedia.org",
)


def release_cover_art_url(event) -> str | None:
    if event.release_id and event.release is not None:
        url = _cover_art_payload_url(event.release.raw_payload)
        if url:
            return url
        if _has_cover_art_archive_front(event.release.raw_payload):
            return f"{COVER_ART_ARCHIVE_BASE_URL}/release/{event.release.mbid}/front-500"

    url = _cover_art_payload_url(event.release_group.raw_payload)
    if url:
        return url
    if _has_cover_art_archive_front(event.release_group.raw_payload):
        return f"{COVER_ART_ARCHIVE_BASE_URL}/release-group/{event.release_group.mbid}/front-500"

    return None


def artist_image_url(artist) -> str | None:
    payload = _payload_dict(artist.raw_payload)
    direct_url = _trusted_image_url(payload.get("image") or payload.get("image_url"))
    if direct_url:
        return direct_url

    for relation in _payload_list(payload.get("relations")):
        relation_payload = _payload_dict(relation)
        if relation_payload.get("target-type") != "url" or relation_payload.get("type") != "image":
            continue
        url_payload = _payload_dict(relation_payload.get("url"))
        resource = _trusted_image_url(url_payload.get("resource"))
        if resource:
            return resource

    return None


def _cover_art_payload_url(payload: Any) -> str | None:
    for image in _payload_list(_payload_dict(payload).get("images")):
        image_payload = _payload_dict(image)
        if not image_payload.get("front", False):
            continue
        thumbnails = _payload_dict(image_payload.get("thumbnails"))
        for key in ("500", "large", "small"):
            thumbnail_url = _trusted_image_url(thumbnails.get(key))
            if thumbnail_url:
                return thumbnail_url
        image_url = _trusted_image_url(image_payload.get("image"))
        if image_url:
            return image_url
    return None


def _has_cover_art_archive_front(payload: Any) -> bool:
    archive = _payload_dict(_payload_dict(payload).get("cover-art-archive"))
    return bool(archive.get("front", False))


def _payload_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _payload_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _trusted_image_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname is None:
        return None
    hostname = parsed.hostname.casefold()
    if any(hostname == host or hostname.endswith(f".{host}") for host in TRUSTED_IMAGE_HOSTS):
        return value
    return None
