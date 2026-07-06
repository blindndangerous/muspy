from releasewatch.models import Artist, ReleaseEvent


def serialize_artist_summary(artist: Artist) -> dict:
    return {
        "mbid": str(artist.mbid),
        "name": artist.name,
        "sort_name": artist.sort_name,
        "disambiguation": artist.disambiguation,
    }


def serialize_release_event(event: ReleaseEvent, *, include_release=True) -> dict:
    release_group = event.release_group
    payload = {
        "id": event.id,
        "mbid": str(release_group.mbid),
        "title": release_group.title,
        "primary_type": release_group.primary_type,
        "secondary_types": release_group.secondary_types,
        "date": _date_or_none(event.event_date),
        "date_precision": event.date_precision,
        "country": event.country,
    }
    if include_release:
        payload["artist"] = serialize_artist_summary(release_group.artist)
        payload["release"] = serialize_release(event.release)
    return payload


def serialize_release(release) -> dict | None:
    if release is None:
        return None
    return {
        "mbid": str(release.mbid),
        "country": release.country,
        "date": _date_or_none(release.release_date),
        "date_precision": release.release_date_precision,
        "status": release.status,
        "media_format": release.media_format,
    }


def serialize_artist_detail(artist: Artist, events) -> dict:
    return {
        "artist": {
            **serialize_artist_summary(artist),
            "type": artist.artist_type,
            "country": artist.country,
            "releases": [
                serialize_release_event(event, include_release=False) for event in events
            ],
        }
    }


def _date_or_none(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()
