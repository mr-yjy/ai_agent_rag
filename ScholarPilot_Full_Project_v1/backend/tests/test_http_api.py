import json
import threading
import unittest
import urllib.error
import urllib.request

from scholarpilot.config import SecurityConfig
from scholarpilot.security import SearchSecurity
from scholarpilot.server import create_server
from scholarpilot.service import LiveSearchError


PROXY_TOKEN = "test-proxy-token-with-at-least-32-characters"


class SuccessfulSearchService:
    def search(
        self,
        query,
        limit,
        *,
        request_id,
        auth_queue_ms=0,
    ):
        del auth_queue_ms
        plan = {
            "originalQuery": query,
            "normalizedQuery": query,
            "mustHave": [],
            "preferred": [],
            "exclude": [],
            "subqueries": [query],
            "retrievalPreference": "balanced",
        }
        return {
            "schemaVersion": "1.0",
            "requestId": request_id,
            "status": "success",
            "degraded": False,
            "provider": "test academic provider",
            "queryPlan": plan,
            "plan": plan,
            "results": [
                {
                    "id": "paper-1",
                    "title": "Academic paper retrieval agents",
                    "rank": 1,
                }
            ][:limit],
            "sourceStatus": [
                {
                    "source": "test",
                    "status": "success",
                    "apiCalls": 1,
                    "resultCount": 1,
                }
            ],
            "stats": {
                "elapsedMs": 12,
                "apiCalls": 1,
                "llmCalls": 0,
                "stageTimings": {},
                "tokenUsage": {},
                "stopReason": "completed",
                "configHash": "test",
                "candidateCount": 1,
            },
        }


class FailingSearchService:
    def search(self, query, limit):
        del query, limit
        raise LiveSearchError(
            "all academic providers failed",
            provider_errors=[
                {
                    "provider": "OpenAlex",
                    "message": "upstream unavailable",
                }
            ],
        )


class HttpApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.security = SearchSecurity(
            SecurityConfig(
                backend_proxy_token=PROXY_TOKEN,
                rate_limit_requests=100,
                max_concurrent_searches=8,
            )
        )
        cls.server = create_server(
            "127.0.0.1",
            0,
            security=cls.security,
        )
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(
            target=cls.server.serve_forever,
            daemon=True,
        )
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_health_endpoint(self) -> None:
        with urllib.request.urlopen(
            f"{self.base_url}/api/health",
            timeout=3,
        ) as response:
            payload = json.load(response)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["service"], "scholarpilot-python")
        self.assertEqual(payload["backend"]["adapter"], "stdlib")
        self.assertIn("llm", payload)
        self.assertIn("configured", payload["llm"])
        self.assertIn("model", payload["llm"])
        self.assertNotIn("apiKey", payload["llm"])
        self.assertIn("academicSources", payload)
        self.assertIn("openalex", payload["academicSources"])
        self.assertIn(
            "apiKeyConfigured",
            payload["academicSources"]["openalex"],
        )

    def test_search_endpoint(self) -> None:
        server = create_server(
            "127.0.0.1",
            0,
            service=SuccessfulSearchService(),  # type: ignore[arg-type]
            security=SearchSecurity(
                SecurityConfig(
                    backend_proxy_token=PROXY_TOKEN,
                    rate_limit_requests=100,
                )
            ),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body = json.dumps(
                {
                    "query": "academic paper retrieval agents",
                    "limit": 5,
                },
            ).encode("utf-8")
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/search",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {PROXY_TOKEN}",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                payload = json.load(response)

            self.assertEqual(payload["schemaVersion"], "1.0")
            self.assertTrue(payload["requestId"])
            self.assertEqual(payload["status"], "success")
            self.assertEqual(len(payload["results"]), 1)
            self.assertEqual(payload["results"][0]["rank"], 1)
            self.assertNotIn("mode", payload)
            self.assertIn("subqueries", payload["plan"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_unauthorized_search_returns_401(self) -> None:
        request = urllib.request.Request(
            f"{self.base_url}/api/search",
            data=json.dumps(
                {"query": "academic paper retrieval agent"}
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(context.exception.code, 401)
        payload = json.load(context.exception)
        context.exception.close()
        self.assertEqual(payload["error"]["code"], "unauthorized")
        self.assertTrue(payload["error"]["requestId"])

    def test_removed_mode_field_is_rejected(self) -> None:
        request = urllib.request.Request(
            f"{self.base_url}/api/search",
            data=json.dumps(
                {
                    "query": "academic paper retrieval agent",
                    "mode": "demo",
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {PROXY_TOKEN}",
            },
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(context.exception.code, 400)
        payload = json.load(context.exception)
        context.exception.close()
        self.assertEqual(payload["error"]["code"], "invalid_request")
        self.assertNotIn("results", payload)

    def test_backend_failure_returns_502(self) -> None:
        server = create_server(
            "127.0.0.1",
            0,
            service=FailingSearchService(),  # type: ignore[arg-type]
            security=SearchSecurity(
                SecurityConfig(
                    backend_proxy_token=PROXY_TOKEN,
                    rate_limit_requests=100,
                )
            ),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/search",
                data=json.dumps(
                    {"query": "academic paper retrieval agent"}
                ).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {PROXY_TOKEN}",
                },
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as context:
                urllib.request.urlopen(request, timeout=3)
            self.assertEqual(context.exception.code, 502)
            payload = json.load(context.exception)
            context.exception.close()
            self.assertEqual(
                payload["error"]["code"],
                "live_backend_failed",
            )
            self.assertTrue(payload["error"]["requestId"])
            self.assertNotIn("results", payload)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
