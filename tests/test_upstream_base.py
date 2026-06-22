import time
from datetime import date

import httpx
import pytest

from releasewatch.models import DatePrecision
from releasewatch.upstreams.base import (
    FixedIntervalThrottle,
    UpstreamAuthError,
    UpstreamClient,
    UpstreamNotFound,
    UpstreamRateLimited,
    UpstreamUnavailable,
    parse_partial_date,
    redact_upstream_payload,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026", (date(2026, 1, 1), DatePrecision.YEAR)),
        ("2026-06", (date(2026, 6, 1), DatePrecision.MONTH)),
        ("2026-06-21", (date(2026, 6, 21), DatePrecision.DAY)),
        ("", (None, "")),
    ],
)
def test_parse_partial_date_returns_date_and_precision(value, expected):
    assert parse_partial_date(value) == expected


def test_redact_upstream_payload_redacts_nested_sensitive_values():
    payload = {
        "token": "top-secret",
        "nested": {
            "api_key": "secret-key",
            "items": [{"access_token": "nested-secret", "name": "kept"}],
        },
    }

    assert redact_upstream_payload(payload) == {
        "token": "[redacted]",
        "nested": {
            "api_key": "[redacted]",
            "items": [{"access_token": "[redacted]", "name": "kept"}],
        },
    }


def test_upstream_client_maps_http_429_to_rate_limited():
    def handler(request):
        return httpx.Response(429, json={"error": "slow down"})

    client = UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(UpstreamRateLimited) as exc_info:
        client.get_json("/limited")

    assert exc_info.value.status_code == 429
    assert exc_info.value.payload == {"error": "slow down"}


@pytest.mark.parametrize(
    ("status_code", "exception_type"),
    [
        (401, UpstreamAuthError),
        (403, UpstreamAuthError),
        (404, UpstreamNotFound),
        (500, UpstreamUnavailable),
        (503, UpstreamRateLimited),
    ],
)
def test_upstream_client_maps_http_status_to_specific_exception(status_code, exception_type):
    def handler(request):
        return httpx.Response(status_code, json={"error": "provider error"})

    client = UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(exception_type) as exc_info:
        client.get_json("/path")

    assert exc_info.value.status_code == status_code
    assert exc_info.value.payload == {"error": "provider error"}


def test_upstream_client_sends_json_headers():
    seen_headers = {}

    def handler(request):
        seen_headers.update(request.headers)
        return httpx.Response(200, json={"ok": True})

    client = UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.get_json("/path") == {"ok": True}
    assert seen_headers["user-agent"] == "muspy/0.1.0 (https://example.invalid/contact)"
    assert seen_headers["accept"] == "application/json"


def test_upstream_client_maps_invalid_json_to_unavailable_with_redacted_payload():
    def handler(request):
        return httpx.Response(200, text='{"api_key": "secret"')

    client = UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(UpstreamUnavailable) as exc_info:
        client.get_json("/bad-json")

    assert exc_info.value.status_code == 200
    assert exc_info.value.payload == {"body": "[invalid json]"}


def test_fixed_interval_throttle_waits_between_calls(monkeypatch):
    current = {"value": 10.0}
    sleeps = []
    monkeypatch.setattr(time, "monotonic", lambda: current["value"])
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))

    throttle = FixedIntervalThrottle(interval_seconds=1.0)
    throttle.wait()
    throttle.wait()

    assert sleeps == [1.0]
