import unittest

from scholarpilot.config import SecurityConfig
from scholarpilot.security import (
    AuthenticationError,
    ConcurrencyLimitExceeded,
    RateLimitExceeded,
    SearchSecurity,
)


class SearchSecurityTest(unittest.TestCase):
    def test_authentication_rate_limit_and_cors_are_fail_closed(self) -> None:
        proxy_secret = "proxy-secret-with-at-least-32-characters"
        security = SearchSecurity(
            SecurityConfig(
                backend_proxy_token=proxy_secret,
                cors_allowed_origins=("https://app.example.com",),
                rate_limit_requests=2,
                rate_limit_window_seconds=60,
                max_concurrent_searches=1,
            )
        )
        with self.assertRaises(AuthenticationError):
            security.authorize(None)
        security.authorize(f"Bearer {proxy_secret}")
        self.assertTrue(security.origin_allowed("https://app.example.com"))
        self.assertFalse(security.origin_allowed("https://evil.example.com"))

        with security.admit(["ip:127.0.0.1"]):
            pass
        with security.admit(["ip:127.0.0.1"]):
            pass
        with self.assertRaises(RateLimitExceeded):
            with security.admit(["ip:127.0.0.1"]):
                pass

    def test_concurrency_limit_rejects_without_waiting(self) -> None:
        security = SearchSecurity(
            SecurityConfig(
                backend_proxy_token="proxy-secret-with-at-least-32-characters",
                rate_limit_requests=10,
                max_concurrent_searches=1,
            )
        )
        with security.admit(["ip:first"]):
            with self.assertRaises(ConcurrencyLimitExceeded):
                with security.admit(["ip:second"]):
                    pass


if __name__ == "__main__":
    unittest.main()
