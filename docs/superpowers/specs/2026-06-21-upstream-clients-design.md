# Upstream clients design

## Purpose

Add a small, tested client layer for external music services before any sync or import workflow uses network calls.

This layer covers:

- MusicBrainz as canonical metadata source.
- ListenBrainz for user import and future freshness signals.
- Last.fm for user import only.

No workflow code should call these providers directly. Import and sync jobs should depend on typed client methods.

## Sources checked

- MusicBrainz API: https://musicbrainz.org/doc/MusicBrainz_API
- MusicBrainz rate limiting: https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting
- ListenBrainz API: https://listenbrainz.readthedocs.io/en/latest/users/api/index.html
- Last.fm API intro: https://www.last.fm/api/intro
- Last.fm API terms: https://www.last.fm/api/tos
- Last.fm scrobble docs: https://www.last.fm/api/show/track.scrobble
- HTTPX docs via Context7: timeouts default to 5 seconds of network inactivity, `raise_for_status()` raises `HTTPStatusError`, and `MockTransport` supports transport-level tests.

## External constraints

MusicBrainz:

- API root is `https://musicbrainz.org/ws/2/`.
- JSON responses should be requested with `fmt=json` or `Accept: application/json`.
- Client must send a meaningful `User-Agent`.
- Client must stay at or below 1 request per second per app/IP unless we have a separate agreement.
- HTTP 503 can mean provider throttling.

ListenBrainz:

- API root is `https://api.listenbrainz.org`.
- HTTPS only.
- Authenticated requests use `Authorization: Token <token>`.
- Rate limit metadata comes from `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset-In` response headers.

Last.fm:

- API usage needs an API key.
- Terms require attribution, suitable caching based on response headers, respect for provider rate limits, and no circumvention.
- Store only import data needed by this app. Do not treat Last.fm as canonical metadata.

## Architecture

Use synchronous `httpx.Client` wrappers for now. The Django app is server-rendered and the first sync/import workers are synchronous management or task-style code, so async clients add complexity without current benefit.

Create `releasewatch/upstreams/`:

- `base.py`: shared `UpstreamClient`, `UpstreamError`, `UpstreamRateLimited`, `UpstreamUnavailable`, `UpstreamAuthError`, `UpstreamNotFound`, timeout defaults, response parsing, redacted logging payload helper, and simple rate-limit policy hooks.
- `musicbrainz.py`: typed methods for artist lookup/search and release group browse/lookup.
- `listenbrainz.py`: typed methods for user artist import and optional freshness reads.
- `lastfm.py`: typed methods for user top artists import.

All clients accept an injected `httpx.Client` or transport so tests use `httpx.MockTransport`. Tests must not call live services.

## Rate and retry policy

Do not add broad automatic retries yet. Retry behavior can hide provider abuse and make tests flaky.

Initial policy:

- Set explicit timeout.
- Add MusicBrainz fixed throttle: one request per second by default.
- Parse ListenBrainz rate limit headers and expose them on the client response metadata.
- Convert HTTP 429 and MusicBrainz 503 throttle responses to `UpstreamRateLimited`.
- Convert provider 5xx to `UpstreamUnavailable`.
- Convert auth failures to `UpstreamAuthError`.
- Convert 404 to `UpstreamNotFound`.
- Leave caller/job scheduling responsible for persistence and retry timing through `SyncState.retry_after`.

## Data mapping

Client methods should return small dataclasses, not raw JSON:

- `UpstreamArtist`: `mbid`, `name`, `sort_name`, `disambiguation`, `artist_type`, `country`, `aliases`, `raw_payload`.
- `UpstreamReleaseGroup`: `mbid`, `title`, `primary_type`, `secondary_types`, `first_release_date`, `first_release_precision`, `raw_payload`.
- `UpstreamRelease`: `mbid`, `country`, `release_date`, `release_date_precision`, `status`, `media_format`, `raw_payload`.
- `ImportedArtist`: `source_name`, `source_identifier`, `mbid`, `raw_payload`.

Date parsing must preserve precision. `2026`, `2026-06`, and `2026-06-21` map to the stored date plus `DatePrecision.YEAR`, `DatePrecision.MONTH`, or `DatePrecision.DAY`.

## Security

- Never log ListenBrainz tokens, Last.fm API secrets, session keys, or signed URLs.
- Keep Last.fm API key and secret in environment-backed settings.
- Do not persist provider credentials in this task.
- Do not expose provider tokens in admin search fields or raw error messages.
- Network tests use local mock transports only.

## Testing

Use TDD with mocked transports.

Coverage must include:

- Successful MusicBrainz artist/release mapping.
- MusicBrainz user-agent and one-request-per-second throttle behavior.
- Date precision parsing.
- ListenBrainz authorization header and rate-limit header parsing.
- Last.fm unsigned `user.getTopArtists` import call shape.
- Error mapping for 404, 401/403, 429, 503, invalid JSON, and timeout.
- Secret redaction in stored/loggable payloads.

Coverage floor stays at 96% and only moves up.

## Non-goals

- No background scheduler implementation.
- No live provider smoke tests.
- No OAuth setup.
- No provider credential storage UI.
- No cache persistence beyond fields already present in domain models.
