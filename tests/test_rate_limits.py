import hashlib
from typing import cast

import pytest
from django.core.cache import cache, caches
from django.test import RequestFactory, override_settings


@pytest.fixture(autouse=True)
def locmem_cache(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "rate-limit-tests",
        }
    }
    caches.close_all()
    cache.clear()
    yield
    cache.clear()
    caches.close_all()


def test_check_rate_limit_allows_requests_below_limit():
    from releasewatch.rate_limits import check_rate_limit

    request = RequestFactory().get("/artists/search/", REMOTE_ADDR="192.0.2.10")

    first = check_rate_limit(
        request,
        scope="artist-search",
        limit=2,
        window_seconds=60,
        identity="ip",
    )
    second = check_rate_limit(
        request,
        scope="artist-search",
        limit=2,
        window_seconds=60,
        identity="ip",
    )

    assert first.allowed is True
    assert first.remaining == 1
    assert second.allowed is True
    assert second.remaining == 0


def test_check_rate_limit_blocks_requests_over_limit():
    from releasewatch.rate_limits import check_rate_limit

    request = RequestFactory().get("/artists/search/", REMOTE_ADDR="192.0.2.10")

    check_rate_limit(request, scope="artist-search", limit=1, window_seconds=60, identity="ip")
    result = check_rate_limit(
        request,
        scope="artist-search",
        limit=1,
        window_seconds=60,
        identity="ip",
    )

    assert result.allowed is False
    assert result.remaining == 0
    assert result.retry_after_seconds > 0


def test_rate_limit_cache_key_hashes_sensitive_values():
    from releasewatch.rate_limits import rate_limit_key

    identity_value = "person@example.test"
    plain_digest = hashlib.sha256(identity_value.encode("utf-8")).hexdigest()

    key = rate_limit_key(
        scope="login",
        identity_parts=("username", identity_value),
        window_seconds=60,
        now_seconds=120,
    )

    assert identity_value not in key
    assert plain_digest not in key
    assert "username" in key
    assert key.startswith("releasewatch:ratelimit:login:username:")


def test_user_or_ip_identity_uses_user_id_for_authenticated_user():
    from django.contrib.auth.models import User

    from releasewatch.rate_limits import identity_parts_for_request

    user = User(id=1, username="listener")
    request = RequestFactory().get("/dashboard/", REMOTE_ADDR="192.0.2.10")
    request.user = user

    assert identity_parts_for_request(request, "user_or_ip") == ("user", str(user.id))


def test_user_or_ip_identity_uses_ip_for_anonymous_user():
    from django.contrib.auth.models import AnonymousUser

    from releasewatch.rate_limits import identity_parts_for_request

    request = RequestFactory().get("/releases/", REMOTE_ADDR="192.0.2.10")
    request.user = AnonymousUser()

    assert identity_parts_for_request(request, "user_or_ip") == ("ip", "192.0.2.10")


def test_user_identity_falls_back_to_anonymous_ip_for_anonymous_user():
    from django.contrib.auth.models import AnonymousUser

    from releasewatch.rate_limits import identity_parts_for_request

    request = RequestFactory().get("/imports/", REMOTE_ADDR="192.0.2.20")
    request.user = AnonymousUser()

    assert identity_parts_for_request(request, "user") == ("anonymous", "192.0.2.20")


def test_identity_parts_rejects_unexpected_identity_value():
    from releasewatch.rate_limits import Identity, identity_parts_for_request

    request = RequestFactory().get("/releases/", REMOTE_ADDR="192.0.2.10")

    with pytest.raises(ValueError, match="Unsupported rate limit identity"):
        identity_parts_for_request(request, cast(Identity, "email"))


def test_rate_limited_response_uses_429_template():
    from releasewatch.rate_limits import rate_limited_response

    response = rate_limited_response(RequestFactory().get("/"), retry_after_seconds=30)

    assert response.status_code == 429
    assert response["Retry-After"] == "30"
    assert b"Too many requests" in response.content


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.dummy.DummyCache",
        }
    }
)
def test_dummy_cache_backend_is_rejected_for_protected_limits():
    from releasewatch.rate_limits import RateLimitUnavailable, check_rate_limit

    request = RequestFactory().get("/artists/search/", REMOTE_ADDR="192.0.2.10")

    with pytest.raises(RateLimitUnavailable):
        check_rate_limit(request, scope="artist-search", limit=1, window_seconds=60, identity="ip")


def test_missing_cache_counter_is_rejected(mocker):
    from releasewatch.rate_limits import RateLimitUnavailable, check_rate_limit

    request = RequestFactory().get("/artists/search/", REMOTE_ADDR="192.0.2.10")
    mocker.patch("releasewatch.rate_limits.cache.incr", return_value=None)

    with pytest.raises(RateLimitUnavailable, match="did not return a counter"):
        check_rate_limit(request, scope="artist-search", limit=1, window_seconds=60, identity="ip")
