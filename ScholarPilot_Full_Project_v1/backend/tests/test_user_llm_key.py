import json
import unittest

from scholarpilot.config import LLMConfig
from scholarpilot.llm_client import LLMClient
from scholarpilot.service import SearchService


class UserLlmKeyTest(unittest.TestCase):
    def test_default_service_never_loads_a_shared_llm_key(self) -> None:
        service = SearchService()

        self.assertFalse(service.use_llm)
        self.assertEqual(service.credential_source, "none")
        self.assertEqual(service.llm.config.api_key, "")

    def test_request_service_uses_an_isolated_user_key(self) -> None:
        server_key = "sk-" + ("s" * 32)
        user_key = "sk-" + ("u" * 32)
        service = SearchService(
            llm_client=LLMClient(LLMConfig(api_key=server_key))
        )

        request_service = service.with_user_api_key(user_key)

        self.assertEqual(request_service.llm.config.api_key, user_key)
        self.assertEqual(
            request_service.llm.config.base_url,
            "https://api.deepseek.com",
        )
        self.assertEqual(
            request_service.llm.config.model,
            "deepseek-v4-pro",
        )
        self.assertEqual(
            request_service.llm_info()["credentialSource"],
            "user",
        )
        self.assertEqual(service.llm.config.api_key, server_key)
        self.assertNotIn(
            user_key,
            json.dumps(request_service.llm_info()),
        )

    def test_invalid_user_key_is_rejected(self) -> None:
        service = SearchService(
            llm_client=LLMClient(LLMConfig(api_key=""))
        )

        with self.assertRaises(ValueError):
            service.with_user_api_key("short")

    def test_flash_model_can_be_selected(self) -> None:
        user_key = "sk-" + ("f" * 32)
        service = SearchService(
            llm_client=LLMClient(LLMConfig(api_key=""))
        )

        request_service = service.with_user_api_key(
            user_key,
            "deepseek-v4-flash",
        )

        self.assertEqual(
            request_service.llm.config.model,
            "deepseek-v4-flash",
        )

    def test_unknown_user_model_is_rejected(self) -> None:
        service = SearchService(
            llm_client=LLMClient(LLMConfig(api_key=""))
        )

        with self.assertRaises(ValueError):
            service.with_user_api_key(
                "sk-" + ("x" * 32),
                "untrusted-model",
            )


if __name__ == "__main__":
    unittest.main()
