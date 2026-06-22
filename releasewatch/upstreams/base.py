import time
from dataclasses import dataclass
from datetime import date
from threading import Lock
from typing import Any

import httpx

from releasewatch.models import DatePrecision, redact_payload


@dataclass(frozen=True)
class UpstreamArtistAlias:
    name: str
    sort_name: str
    locale: str
    alias_type: str
    primary: bool


@dataclass(frozen=True)
class UpstreamArtist:
    mbid: str
    name: str
    sort_name: str
    disambiguation: str
    artist_type: str
    country: str
    aliases: list[UpstreamArtistAlias]
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class UpstreamReleaseGroup:
    mbid: str
    title: str
    primary_type: str
    secondary_types: list[str]
    first_release_date: date | None
    first_release_precision: DatePrecision | str
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class UpstreamRelease:
    mbid: str
    country: str
    release_date: date | None
    release_date_precision: DatePrecision | str
    status: str
    media_format: str
    raw_payload: dict[str, Any]


class UpstreamError(Exception):
    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.payload = redact_upstream_payload(payload)


class UpstreamRateLimited(UpstreamError):
    pass


class UpstreamUnavailable(UpstreamError):
    pass


class UpstreamAuthError(UpstreamError):
    pass


class UpstreamNotFound(UpstreamError):
    pass


def parse_partial_date(value: str):
    if not value:
        return None, ""

    try:
        match len(value):
            case 4:
                return date(int(value), 1, 1), DatePrecision.YEAR
            case 7:
                year, month = value.split("-", maxsplit=1)
                return date(int(year), int(month), 1), DatePrecision.MONTH
            case 10:
                year, month, day = value.split("-", maxsplit=2)
                return date(int(year), int(month), int(day)), DatePrecision.DAY
            case _:
                return None, ""
    except ValueError:
        return None, ""


def redact_upstream_payload(value):
    return redact_payload(value)


class FixedIntervalThrottle:
    def __init__(self, interval_seconds: float) -> None:
        self.interval_seconds = interval_seconds
        self._last_called_at: float | None = None

    def wait(self) -> None:
        now = time.monotonic()
        if self._last_called_at is not None:
            elapsed = now - self._last_called_at
            remaining = self.interval_seconds - elapsed
            if remaining > 0:
                time.sleep(remaining)
                now = time.monotonic()
        self._last_called_at = now


class LockedThrottle:
    def __init__(self, throttle: FixedIntervalThrottle) -> None:
        self._throttle = throttle
        self._lock = Lock()

    def wait(self) -> None:
        with self._lock:
            self._throttle.wait()


class UpstreamClient:
    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        provider: str | None = None,
        http_client: httpx.Client | None = None,
        timeout: httpx.Timeout | float | None = None,
        throttle: FixedIntervalThrottle | LockedThrottle | None = None,
        rate_limit_status_codes: set[int] | None = None,
    ) -> None:
        if not user_agent:
            raise ValueError("UpstreamClient requires a User-Agent")

        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.provider = provider or httpx.URL(base_url).host
        self.throttle = throttle
        self.rate_limit_status_codes = rate_limit_status_codes or {429}
        if http_client is not None:
            self.http_client = http_client
            self._owns_http_client = False
        elif timeout is None:
            self.http_client = httpx.Client()
            self._owns_http_client = True
        else:
            self.http_client = httpx.Client(timeout=timeout)
            self._owns_http_client = True

    def close(self) -> None:
        if self._owns_http_client:
            self.http_client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ):
        if self.throttle is not None:
            self.throttle.wait()

        request_headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        if headers is not None:
            request_headers.update(headers)

        try:
            response = self.http_client.get(
                self._url_for_path(path),
                params=params,
                headers=request_headers,
            )
        except httpx.RequestError as exc:
            raise UpstreamUnavailable(
                f"{self.provider} request failed",
                provider=self.provider,
                payload={"error_type": type(exc).__name__},
            ) from exc

        if response.status_code >= 400:
            raise self._error_for_response(response)

        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamUnavailable(
                f"{self.provider} returned invalid JSON",
                provider=self.provider,
                status_code=response.status_code,
                payload=_response_payload(response),
            ) from exc

    def _url_for_path(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            request_url = httpx.URL(path)
            base_url = httpx.URL(self.base_url)
            if (
                request_url.scheme,
                request_url.host,
                request_url.port,
            ) != (
                base_url.scheme,
                base_url.host,
                base_url.port,
            ):
                raise ValueError("UpstreamClient does not allow off-origin absolute URLs")
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def _error_for_response(self, response: httpx.Response) -> UpstreamError:
        exception_type = self._exception_type_for_status(response.status_code)
        return exception_type(
            f"{self.provider} returned HTTP {response.status_code}",
            provider=self.provider,
            status_code=response.status_code,
            payload=_response_payload(response),
        )

    def _exception_type_for_status(self, status_code: int) -> type[UpstreamError]:
        if status_code in self.rate_limit_status_codes:
            return UpstreamRateLimited
        return _exception_type_for_status(status_code)


def _exception_type_for_status(status_code: int) -> type[UpstreamError]:
    if status_code == 429:
        return UpstreamRateLimited
    if status_code in {401, 403}:
        return UpstreamAuthError
    if status_code == 404:
        return UpstreamNotFound
    if status_code >= 500:
        return UpstreamUnavailable
    return UpstreamError


def _response_payload(response: httpx.Response):
    try:
        return response.json()
    except ValueError:
        return {"body": "[invalid json]"}
