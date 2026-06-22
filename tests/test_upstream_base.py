import time
from datetime import date

import httpx
import pytest

from releasewatch.models import DatePrecision
from releasewatch.upstreams.base import (
    FixedIntervalThrottle,
    UpstreamAuthError,
    UpstreamClient,
    UpstreamError,
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
        ("bad-date", (None, "")),
        ("202A", (None, "")),
        ("2026-13", (None, "")),
        ("2026-02-30", (None, "")),
        ("0000", (None, "")),
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
        (503, UpstreamUnavailable),
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


def test_upstream_client_merges_custom_headers():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["authorization"]
        return httpx.Response(200, json={"ok": True})

    client = UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.get_json(
        "/path",
        headers={"Authorization": "Token secret"},
    ) == {"ok": True}
    assert seen == {
        "url": "https://provider.test/path",
        "authorization": "Token secret",
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://other-provider.test/path",
        "http://provider.test/path",
        "https://provider.test:444/path",
    ],
)
def test_upstream_client_rejects_off_origin_absolute_url(url):
    client = UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
    )

    with pytest.raises(ValueError, match="absolute URLs"):
        client.get_json(url)

    client.close()


def test_upstream_client_can_map_503_to_rate_limited_for_provider_policy():
    def handler(request):
        return httpx.Response(503, json={"error": "slow down"})

    client = UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        rate_limit_status_codes={503},
    )

    with pytest.raises(UpstreamRateLimited):
        client.get_json("/path")


def test_upstream_client_requires_user_agent():
    with pytest.raises(ValueError, match="User-Agent"):
        UpstreamClient(base_url="https://provider.test", user_agent="")


def test_upstream_client_accepts_default_and_timeout_http_clients():
    default_client = UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
    )
    timeout_client = UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
        timeout=1.0,
    )

    assert isinstance(default_client.http_client, httpx.Client)
    assert isinstance(timeout_client.http_client, httpx.Client)
    default_client.http_client.close()
    timeout_client.http_client.close()


def test_upstream_client_maps_request_error_to_unavailable():
    def handler(request):
        raise httpx.ConnectError(
            "network down: https://provider.test/path?token=secret",
            request=request,
        )

    client = UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(UpstreamUnavailable) as exc_info:
        client.get_json("/network-error")

    assert exc_info.value.status_code is None
    assert exc_info.value.payload == {"error_type": "ConnectError"}


def test_upstream_client_closes_only_owned_http_client():
    owned_client = UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
    )
    injected_http_client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    )
    injected_client = UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
        http_client=injected_http_client,
    )

    owned_client.close()
    injected_client.close()

    assert owned_client.http_client.is_closed is True
    assert injected_http_client.is_closed is False
    injected_http_client.close()


def test_upstream_client_supports_context_manager_for_owned_client():
    with UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
    ) as client:
        http_client = client.http_client

    assert http_client.is_closed is True


def test_upstream_client_maps_unclassified_client_error_to_upstream_error():
    def handler(request):
        return httpx.Response(400, json={"error": "bad request"})

    client = UpstreamClient(
        base_url="https://provider.test",
        user_agent="muspy/0.1.0 (https://example.invalid/contact)",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(UpstreamError) as exc_info:
        client.get_json("/bad")

    assert exc_info.value.status_code == 400
    assert exc_info.value.payload == {"error": "bad request"}


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

    def fake_sleep(seconds):
        sleeps.append(seconds)
        current["value"] += seconds

    monkeypatch.setattr(time, "sleep", fake_sleep)

    throttle = FixedIntervalThrottle(interval_seconds=1.0)
    throttle.wait()
    throttle.wait()

    assert sleeps == [1.0]


def test_fixed_interval_throttle_skips_sleep_when_interval_elapsed(monkeypatch):
    values = iter([10.0, 12.0])
    sleeps = []
    monkeypatch.setattr(time, "monotonic", lambda: next(values))
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))

    throttle = FixedIntervalThrottle(interval_seconds=1.0)
    throttle.wait()
    throttle.wait()

    assert sleeps == []
