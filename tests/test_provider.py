import threading
import unittest

from examples.mock_provider import MockServer
from rooomtech_router.config import ModelConfig
from rooomtech_router.provider import OpenAICompatibleProvider


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.server = MockServer(("127.0.0.1", 0), "integration-model")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_real_http_adapter(self):
        model = ModelConfig.from_dict(
            {
                "id": "integration",
                "provider": "mock",
                "base_url": f"http://127.0.0.1:{self.server.server_port}/v1",
                "model": "upstream-id",
            }
        )
        response = OpenAICompatibleProvider().chat(
            model,
            {"messages": [{"role": "user", "content": "hello"}]},
            timeout=3,
        )
        self.assertIn("integration-model", response["choices"][0]["message"]["content"])
        self.assertGreater(response["usage"]["total_tokens"], 0)


if __name__ == "__main__":
    unittest.main()

