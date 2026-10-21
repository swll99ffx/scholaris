"""
Optional shared-password gate and lightweight inbound rate limiting.

Local and LAN use need no gate at all. When ``SITE_PASSWORD`` is set (for a
public or shared deployment), every ``/api`` route except the health probe and
the auth endpoints requires a signed session cookie. The cookie is an
HMAC of the expiry timestamp keyed from the password itself, so there is no
second secret to configure and changing the password invalidates old sessions.

Rate limits are per client IP and per minute, protecting the free scholarly
APIs from abusive traffic. They are deliberately generous for one person.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.config import Settings

# Reachable without an access code: the keep-alive/health probe and auth itself.
PUBLIC_PATHS = {
    "/api/health",
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/logout",
}
LOGIN_PATH = "/api/auth/login"
SEARCH_PATH = "/api/research/search"


# ------------------------------------------------------------------ sessions


def _session_key(password: str) -> bytes:
    return hashlib.sha256(f"scholaris-session:{password}".encode("utf-8")).digest()


def issue_session(password: str, ttl_seconds: int) -> str:
    """Return ``<expiry>.<signature>`` for the given access code."""
    expires = int(time.time()) + int(ttl_seconds)
    signature = hmac.new(
        _session_key(password), f"v1:{expires}".encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{expires}.{signature}"


def session_valid(password: str | None, token: str | None) -> bool:
    """True when the token is well-formed, untampered and not expired."""
    if not password or not token:
        return False
    try:
        expires_text, signature = token.split(".", 1)
        expires = int(expires_text)
    except (ValueError, AttributeError):
        return False
    if expires < int(time.time()):
        return False
    expected = hmac.new(
        _session_key(password), f"v1:{expires}".encode("ascii"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def password_matches(expected: str, supplied: str) -> bool:
    return hmac.compare_digest(
        expected.encode("utf-8"), (supplied or "").encode("utf-8")
    )


def request_is_https(request: Request) -> bool:
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return proto == "https" or request.url.scheme == "https"


def cookie_secure(settings: Settings, request: Request) -> bool:
    mode = (settings.cookie_secure or "auto").strip().lower()
    if mode in {"1", "true", "yes", "on"}:
        return True
    if mode in {"0", "false", "no", "off"}:
        return False
    return request_is_https(request)


def client_ip(request: Request) -> str:
    # Proxies append the address they saw, so the right-most entry is the
    # client as seen by the closest trusted proxy. Reading the left-most entry
    # would let a caller prepend a fake IP and dodge the rate limits.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else "unknown"


# ------------------------------------------------------------- rate limiting


class SlidingWindowLimiter:
    """A tiny in-process sliding-window counter (one uvicorn worker)."""

    def __init__(self, window_seconds: float = 60.0) -> None:
        self.window_seconds = window_seconds
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, bucket: str, key: str, limit: int) -> tuple[bool, int]:
        """Record a hit. Returns ``(allowed, retry_after_seconds)``."""
        if limit <= 0:
            return True, 0
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault((bucket, key), deque())
            while hits and now - hits[0] >= self.window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = max(1, int(self.window_seconds - (now - hits[0])) + 1)
                return False, retry_after
            hits.append(now)
            if len(self._hits) > 5_000:
                self._hits = {entry: values for entry, values in self._hits.items() if values}
            return True, 0


# ----------------------------------------------------------------- middleware


class AccessMiddleware(BaseHTTPMiddleware):
    """Apply the inbound rate limits, then the optional password gate."""

    def __init__(
        self,
        app: Callable,
        settings: Settings,
    ) -> None:
        super().__init__(app)
        self.settings = settings
        self.limiter = SlidingWindowLimiter()

    def _limit(self, path: str) -> tuple[str, int]:
        if path == LOGIN_PATH:
            return "login", self.settings.login_rate_limit_per_minute
        if path == SEARCH_PATH:
            return "search", self.settings.search_rate_limit_per_minute
        if path.startswith("/api/summarize/"):
            return "summarize", self.settings.summarize_rate_limit_per_minute
        return "api", self.settings.rate_limit_per_minute

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if request.method == "OPTIONS" or not path.startswith("/api/"):
            return await call_next(request)

        if self.settings.rate_limit_enabled:
            bucket, limit = self._limit(path)
            allowed, retry_after = self.limiter.hit(bucket, client_ip(request), limit)
            if not allowed:
                return JSONResponse(
                    {"detail": "Too many requests. Please wait a moment and try again."},
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                )

        if path in PUBLIC_PATHS or not self.settings.site_password:
            return await call_next(request)

        token = request.cookies.get(self.settings.session_cookie_name)
        if not session_valid(self.settings.site_password, token):
            return JSONResponse({"detail": "Access code required."}, status_code=401)
        return await call_next(request)
