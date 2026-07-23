import json
import threading
import unittest
import urllib.request

from scholarpilot.server import create_server


class HttpApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = create_server("127.0.0.1", 0)
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
        with urllib.request.urlopen(f"{self.base_url}/api/health", timeout=3) as response:
            payload = json.load(response)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "scholarpilot-python")

    def test_search_endpoint(self) -> None:
        body = json.dumps(
            {
                "query": "寻找2024年以后使用查询分解进行学术检索的LLM Agent论文",
                "mode": "demo",
                "limit": 5,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/search",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.load(response)

        self.assertEqual(payload["mode"], "demo")
        self.assertEqual(len(payload["results"]), 5)
        self.assertEqual(payload["results"][0]["rank"], 1)
        self.assertIn("subqueries", payload["plan"])
        self.assertGreaterEqual(payload["stats"]["candidateCount"], 5)


if __name__ == "__main__":
    unittest.main()

