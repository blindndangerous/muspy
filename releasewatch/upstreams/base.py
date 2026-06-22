import time
from datetime import date
from typing import Any

import httpx

from releasewatch.models import DatePrecision, redact_payload


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


class UpstreamClient:
    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        provider: str | None = None,
        http_client: httpx.Client | None = None,
        timeout: httpx.Timeout | float | None = None,
        throttle: FixedIntervalThrottle | None = None,
    ) -> None:
        if not user_agent:
            raise ValueError("UpstreamClient requires a User-Agent")

        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.provider = provider or httpx.URL(base_url).host
        self.throttle = throttle
        if http_client is not None:
            self.http_client = http_client
        elif timeout is None:
            self.http_client = httpx.Client()
        else:
            self.http_client = httpx.Client(timeout=timeout)

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
                payload={"error": str(exc)},
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
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def _error_for_response(self, response: httpx.Response) -> UpstreamError:
        exception_type = _exception_type_for_status(response.status_code)
        return exception_type(
            f"{self.provider} returned HTTP {response.status_code}",
            provider=self.provider,
            status_code=response.status_code,
            payload=_response_payload(response),
        )


def _exception_type_for_status(status_code: int) -> type[UpstreamError]:
    if status_code in {429, 503}:
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
