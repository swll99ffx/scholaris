"""Offline tests for the shared-password gate and inbound rate limiting."""

from __future__ import annotations

import time
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.access import (
    AccessMiddleware,
    SlidingWindowLimiter,
    cookie_secure,
    issue_session,
    password_matches,
    session_valid,
)

COOKIE = "scholaris_session"


def build_client(password: str = "secret", **overrides) -> tuple[TestClient, Settings]:
    config = dict(
        site_password=password,
        session_cookie_name=COOKIE,
        rate_limit_enabled=False,
    )
    config.update(overrides)
    settings = Settings(**config)

    app = FastAPI()
    app.add_middleware(AccessMiddleware, settings=settings)

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/private")
    def private() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/research/search")
    def search() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/auth/login")
    def login() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app), settings


class SessionTokenTest(unittest.TestCase):
    def test_round_trip(self):
        token = issue_session("secret", 3600)
        self.assertTrue(session_valid("secret", token))
        self.assertFalse(session_valid("wrong", token))
        self.assertFalse(session_valid("secret", token + "0"))
        self.assertFalse(session_valid("secret", None))
        self.assertFalse(session_valid("secret", "not-a-token"))

    def test_expired_session_is_rejected(self):
        token = issue_session("secret", -5)
        self.assertFalse(session_valid("secret", token))

    def test_password_comparison(self):
        self.assertTrue(password_matches("open sesame", "open sesame"))
        self.assertFalse(password_matches("open sesame", "Open sesame"))
        self.assertFalse(password_matches("open sesame", ""))


class RateLimiterTest(unittest.TestCase):
    def test_limit_and_window(self):
        limiter = SlidingWindowLimiter(window_seconds=0.05)
        self.assertEqual(limiter.hit("api", "1.1.1.1", 2), (True, 0))
        self.assertEqual(limiter.hit("api", "1.1.1.1", 2), (True, 0))
        allowed, retry_after = limiter.hit("api", "1.1.1.1", 2)
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry_after, 1)
        time.sleep(0.06)
        self.assertTrue(limiter.hit("api", "1.1.1.1", 2)[0])

    def test_limits_are_per_ip(self):
        limiter = SlidingWindowLimiter()
        self.assertTrue(limiter.hit("api", "1.1.1.1", 1)[0])
        self.assertTrue(limiter.hit("api", "2.2.2.2", 1)[0])
        self.assertFalse(limiter.hit("api", "1.1.1.1", 1)[0])


class GateMiddlewareTest(unittest.TestCase):
    def test_private_route_requires_session(self):
        client, _ = build_client()
        response = client.get("/api/private")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Access code required.")

    def test_valid_cookie_grants_access(self):
        client, _ = build_client()
        client.cookies.set(COOKIE, issue_session("secret", 3600))
        self.assertEqual(client.get("/api/private").status_code, 200)

    def test_health_and_auth_routes_stay_public(self):
        client, _ = build_client()
        self.assertEqual(client.get("/api/health").status_code, 200)
        self.assertEqual(client.post("/api/auth/login").status_code, 200)

    def test_gate_is_disabled_without_a_password(self):
        client, _ = build_client(password="")
        self.assertEqual(client.get("/api/private").status_code, 200)

    def test_rate_limit_returns_429(self):
        client, _ = build_client(password="", rate_limit_enabled=True, rate_limit_per_minute=2)
        self.assertEqual(client.get("/api/private").status_code, 200)
        self.assertEqual(client.get("/api/private").status_code, 200)
        response = client.get("/api/private")
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response.headers)

    def test_login_has_its_own_stricter_limit(self):
        client, _ = build_client(
            password="",
            rate_limit_enabled=True,
            rate_limit_per_minute=50,
            login_rate_limit_per_minute=2,
        )
        self.assertEqual(client.post("/api/auth/login").status_code, 200)
        self.assertEqual(client.post("/api/auth/login").status_code, 200)
        self.assertEqual(client.post("/api/auth/login").status_code, 429)

    def test_search_has_its_own_limit(self):
        client, _ = build_client(
            password="",
            rate_limit_enabled=True,
            rate_limit_per_minute=50,
            search_rate_limit_per_minute=1,
        )
        self.assertEqual(client.get("/api/research/search").status_code, 200)
        self.assertEqual(client.get("/api/research/search").status_code, 429)

    def test_forwarded_for_is_used_for_the_client_key(self):
        client, _ = build_client(password="", rate_limit_enabled=True, rate_limit_per_minute=1)
        self.assertEqual(
            client.get("/api/private", headers={"X-Forwarded-For": "9.9.9.9"}).status_code,
            200,
        )
        self.assertEqual(
            client.get("/api/private", headers={"X-Forwarded-For": "8.8.8.8"}).status_code,
            200,
        )
        self.assertEqual(
            client.get("/api/private", headers={"X-Forwarded-For": "9.9.9.9"}).status_code,
            429,
        )


class CookieSecureTest(unittest.TestCase):
    def test_auto_mode_detects_https_behind_a_proxy(self):
        from starlette.requests import Request

        settings = Settings(cookie_secure="auto")

        def make_request(headers: list[tuple[bytes, bytes]], scheme: str = "http"):
            return Request(
                {
                    "type": "http",
                    "method": "POST",
                    "scheme": scheme,
                    "path": "/api/auth/login",
                    "headers": headers,
                    "client": ("127.0.0.1", 1234),
                }
            )

        https = make_request([(b"x-forwarded-proto", b"https")])
        plain = make_request([])
        self.assertTrue(cookie_secure(settings, https))
        self.assertFalse(cookie_secure(settings, plain))
        self.assertTrue(cookie_secure(Settings(cookie_secure="true"), plain))
        self.assertFalse(cookie_secure(Settings(cookie_secure="false"), https))


class MainAppAccessTest(unittest.TestCase):
    """End-to-end login flow against the real application."""

    def setUp(self):
        from app.main import app, settings

        self.settings = settings
        self.original_password = settings.site_password
        settings.site_password = "test-code"
        self.client = TestClient(app)

    def tearDown(self):
        self.settings.site_password = self.original_password

    def test_login_sets_a_cookie_and_unlocks_the_api(self):
        status = self.client.get("/api/auth/status").json()
        self.assertEqual(status, {"required": True, "authenticated": False})

        self.assertEqual(self.client.get("/api/research/library").status_code, 401)

        wrong = self.client.post("/api/auth/login", json={"password": "nope"})
        self.assertEqual(wrong.status_code, 401)

        right = self.client.post("/api/auth/login", json={"password": "test-code"})
        self.assertEqual(right.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/status").json()["authenticated"], True)
        self.assertEqual(self.client.get("/api/research/library").status_code, 200)

        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/research/library").status_code, 401)

    def test_health_stays_public(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
