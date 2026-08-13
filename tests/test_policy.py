import unittest

from rooomtech_router.policy import detect_capabilities, detect_data_class, estimate_tokens


class PolicyTests(unittest.TestCase):
    def test_detects_secret_as_restricted(self):
        level, reasons = detect_data_class("api_key = sk-abcdefghijklmnopqrstuvwxyz1234")
        self.assertEqual(level, "restricted")
        self.assertIn("api_credential", reasons)

    def test_detects_japanese_confidential_marker(self):
        level, reasons = detect_data_class("この資料は社外秘です")
        self.assertEqual(level, "confidential")
        self.assertIn("confidential_marker", reasons)

    def test_capability_detection(self):
        body = {"tools": [{"type": "function"}], "response_format": {"type": "json_object"}}
        messages = [
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": "https://example.invalid/a.png"}}],
            }
        ]
        self.assertEqual(
            set(detect_capabilities(body, messages)), {"chat", "json", "tools", "vision"}
        )

    def test_token_estimator_handles_japanese(self):
        self.assertGreater(estimate_tokens("日本語の長い文章です" * 20), 20)


if __name__ == "__main__":
    unittest.main()

