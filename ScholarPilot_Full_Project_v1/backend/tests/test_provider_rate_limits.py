import unittest
import urllib.error
import urllib.parse
from email.message import Message
from unittest.mock import patch

from scholarpilot.budget import SearchDeadline
from scholarpilot.models import QueryPlan
from scholarpilot.providers import OpenAlexProvider, ProviderError
from scholarpilot.search_agent import _safe_provider_error


def _plan(*queries: str) -> QueryPlan:
    return QueryPlan(
        original_query="academic paper retrieval",
        normalized_query="academic paper retrieval",
        subqueries=list(queries),
    )


def _rate_limit_error(retry_after: str) -> urllib.error.HTTPError:
    headers = Message()
    headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        url="https://api.openalex.org/works",
        code=429,
        msg="Too Many Requests",
        hdrs=headers,
        fp=None,
    )


class OpenAlexRateLimitTest(unittest.TestCase):
    def test_openalex_query_removes_unsupported_wildcards(self) -> None:
        provider = OpenAlexProvider(api_key="test-key")
        url = provider._build_url(
            '("large language model" OR LLM) AND agent* AND retrieval?',
            _plan("fallback query"),
        )
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)[
            "search"
        ][0]

        self.assertNotIn("*", query)
        self.assertNotIn("?", query)
        self.assertIn("agent", query)
        self.assertIn("AND", query)

    def test_long_retry_after_opens_circuit_and_stops_subqueries(self) -> None:
        provider = OpenAlexProvider(
            api_key="",
            max_retries=1,
            max_retry_wait_seconds=3,
        )
        with patch(
            "scholarpilot.providers.urllib.request.urlopen",
            side_effect=_rate_limit_error("33036"),
        ) as urlopen:
            with self.assertRaises(ProviderError) as context:
                provider.search(_plan("one", "two", "three"))

        error = context.exception
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(error.api_calls, 1)
        self.assertEqual(error.status_code, 429)
        self.assertEqual(error.retry_after_seconds, 33036)
        self.assertIn("OPENALEX_API_KEY", error.user_action or "")

    def test_retry_after_exceeding_deadline_is_not_slept_or_retried(
        self,
    ) -> None:
        provider = OpenAlexProvider(
            api_key="test-key",
            max_retries=1,
            max_retry_wait_seconds=60,
        )
        deadline = SearchDeadline(
            "req-retry-after-budget",
            total_seconds=0.5,
        )
        with (
            patch(
                "scholarpilot.providers.urllib.request.urlopen",
                side_effect=_rate_limit_error("30"),
            ) as urlopen,
            patch("scholarpilot.providers.time.sleep") as sleep,
        ):
            with self.assertRaises(ProviderError) as context:
                provider.search(_plan("one", "two"), deadline=deadline)

        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()
        self.assertEqual(context.exception.status_code, 429)
        self.assertEqual(context.exception.retry_after_seconds, 30)

    def test_open_circuit_avoids_another_network_request(self) -> None:
        provider = OpenAlexProvider(api_key="", max_retries=0)
        provider._rate_limited_until = 10**20
        with patch(
            "scholarpilot.providers.urllib.request.urlopen"
        ) as urlopen:
            with self.assertRaises(ProviderError) as context:
                provider.search(_plan("one"))

        self.assertEqual(urlopen.call_count, 0)
        self.assertEqual(context.exception.api_calls, 0)
        self.assertEqual(context.exception.status_code, 429)

    def test_safe_error_contains_structured_recovery_metadata(self) -> None:
        provider = OpenAlexProvider(api_key="")
        error = ProviderError(
            "rate limited",
            api_calls=1,
            retryable=True,
            status_code=429,
            retry_after_seconds=90,
            user_action="Configure OPENALEX_API_KEY.",
        )
        payload = _safe_provider_error(provider, error)

        self.assertEqual(payload["statusCode"], 429)
        self.assertEqual(payload["retryAfterSeconds"], 90)
        self.assertEqual(
            payload["userAction"],
            "Configure OPENALEX_API_KEY.",
        )


if __name__ == "__main__":
    unittest.main()
