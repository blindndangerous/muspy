import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Literal

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

Identity = Literal["ip", "user", "user_or_ip"]


class RateLimitUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


def check_rate_limit(
    request: HttpRequest,
    *,
    scope: str,
    limit: int,
    window_seconds: int,
    identity: Identity = "user_or_ip",
) -> RateLimitResult:
    now_seconds = int(time.time())
    identity_parts = identity_parts_for_request(request, identity)
    key = rate_limit_key(
        scope=scope,
        identity_parts=identity_parts,
        window_seconds=window_seconds,
        now_seconds=now_seconds,
    )
    window_started_at = now_seconds - (now_seconds % window_seconds)
    retry_after_seconds = window_started_at + window_seconds - now_seconds
    timeout = retry_after_seconds + 1

    try:
        cache.add(key, 0, timeout=timeout)
        count = cache.incr(key)
    except Exception as error:
        raise RateLimitUnavailable("Rate limit backend is unavailable.") from error

    if count is None:
        raise RateLimitUnavailable("Rate limit backend did not return a counter.")

    remaining = max(limit - count, 0)
    return RateLimitResult(
        allowed=count <= limit,
        limit=limit,
        remaining=remaining,
        retry_after_seconds=max(retry_after_seconds, 1),
    )


def identity_parts_for_request(request: HttpRequest, identity: Identity) -> tuple[str, str]:
    if identity not in {"ip", "user", "user_or_ip"}:
        raise ValueError(f"Unsupported rate limit identity: {identity}")
    if identity == "user":
        if request.user.is_authenticated:
            return ("user", str(request.user.id))
        return ("anonymous", client_ip(request))
    if identity == "user_or_ip" and request.user.is_authenticated:
        return ("user", str(request.user.id))
    return ("ip", client_ip(request))


def rate_limit_key(
    *,
    scope: str,
    identity_parts: tuple[str, str],
    window_seconds: int,
    now_seconds: int,
) -> str:
    identity_name, identity_value = identity_parts
    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        identity_value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    window = now_seconds // window_seconds
    return f"releasewatch:ratelimit:{scope}:{identity_name}:{digest}:{window_seconds}:{window}"


def client_ip(request: HttpRequest) -> str:
    return request.META.get("REMOTE_ADDR", "")


def rate_limited_response(
    request: HttpRequest,
    *,
    retry_after_seconds: int,
) -> HttpResponse:
    response = render(
        request,
        "429.html",
        {"retry_after_seconds": retry_after_seconds},
        status=429,
    )
    response["Retry-After"] = str(retry_after_seconds)
    return response


def rate_limit_unavailable_response(request: HttpRequest) -> HttpResponse:
    return render(request, "503.html", status=503)
