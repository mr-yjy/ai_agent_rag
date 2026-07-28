import json
import unittest
from unittest.mock import patch

from scholarpilot.config import LLMConfig
from scholarpilot.llm_client import LLMClient, LLMError, extract_json_items


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        del exc_type, exc, traceback
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class DeepSeekV4ClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = LLMConfig(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model="deepseek-v4-pro",
            max_retries=0,
        )
        self.client = LLMClient(self.config)
        self.messages = [
            {
                "role": "user",
                "content": "Return a JSON object with an ok field.",
            }
        ]

    def test_deepseek_v4_pro_is_the_default_model(self) -> None:
        config = LLMConfig()
        self.assertEqual(config.model, "deepseek-v4-pro")
        self.assertEqual(config.base_url, "https://api.deepseek.com")
        self.assertEqual(config.thinking_mode, "disabled")
        self.assertTrue(config.json_mode)

    def test_non_thinking_json_payload(self) -> None:
        payload = self.client._build_payload(
            self.messages,
            "deepseek-v4-pro",
            0.0,
            1024,
            "disabled",
            "high",
            True,
        )

        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["temperature"], 0.0)
        self.assertEqual(
            payload["response_format"],
            {"type": "json_object"},
        )
        self.assertNotIn("reasoning_effort", payload)

    def test_thinking_payload_omits_unsupported_temperature(self) -> None:
        payload = self.client._build_payload(
            self.messages,
            "deepseek-v4-pro",
            0.7,
            2048,
            "enabled",
            "max",
            True,
        )

        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["reasoning_effort"], "max")
        self.assertNotIn("temperature", payload)

    def test_json_item_parser_accepts_object_and_legacy_array(self) -> None:
        expected = [{"index": 0, "score": 90}]
        self.assertEqual(
            extract_json_items(json.dumps({"items": expected})),
            expected,
        )
        self.assertEqual(extract_json_items(json.dumps(expected)), expected)

    def test_urllib_transport_uses_official_endpoint(self) -> None:
        fake_response = FakeResponse(
            {
                "model": "deepseek-v4-pro",
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            }
        )
        with patch(
            "scholarpilot.llm_client.urllib.request.urlopen",
            return_value=fake_response,
        ) as urlopen:
            result = self.client._urllib_chat(
                self.messages,
                "deepseek-v4-pro",
                0.0,
                1024,
                "disabled",
                "high",
                True,
            )

        request = urlopen.call_args.args[0]
        request_payload = json.loads(request.data)
        self.assertEqual(
            request.full_url,
            "https://api.deepseek.com/chat/completions",
        )
        self.assertEqual(request_payload["model"], "deepseek-v4-pro")
        self.assertEqual(result.content, '{"ok": true}')
        self.assertEqual(result.usage["total_tokens"], 15)
        self.assertEqual(
            self.client.metrics_snapshot()["requestAttempts"],
            1,
        )

    def test_failed_call_records_safe_request_diagnostics(self) -> None:
        metrics_token = self.client.begin_request_metrics()
        try:
            with patch.object(
                self.client,
                "_try_openai_package",
                side_effect=LLMError("request failed"),
            ):
                with self.assertRaises(LLMError):
                    self.client.chat(self.messages)
            metrics = self.client.request_metrics_snapshot()
        finally:
            self.client.end_request_metrics(metrics_token)

        self.assertEqual(metrics["calls"], 1)
        self.assertEqual(metrics["failedCalls"], 1)
        self.assertEqual(metrics["totalTokens"], 0)
        self.assertEqual(metrics["lastFailureStatus"], 0)


if __name__ == "__main__":
    unittest.main()
