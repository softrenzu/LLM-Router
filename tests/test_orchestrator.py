import os
import unittest

from rooomtech_router.orchestrator import RouterService
from rooomtech_router.schemas import RouteConstraints
from rooomtech_router.store import RouterStore

from tests.helpers import FakeProvider, basic_body, make_config


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.store = RouterStore(":memory:")
        self.provider = FakeProvider()
        self.service = RouterService(
            self.config, store=self.store, provider=self.provider
        )

    def tearDown(self):
        self.store.close()

    def test_direct_response_contains_route_receipt(self):
        response, headers = self.service.chat(basic_body(), RouteConstraints())
        self.assertEqual(response["model"], "rooomtech-auto")
        self.assertIn("rooomtech_route", response)
        self.assertEqual(headers["X-Rooomtech-Route-Id"], response["rooomtech_route"]["id"])
        route = self.store.get_route(headers["X-Rooomtech-Route-Id"])
        self.assertEqual(route["status"], "completed")

    def test_cascade_uses_fallback(self):
        self.provider.failures.add("cloud-code")
        body = basic_body(
            "Implement a code function",
            tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
        )
        response, _ = self.service.chat(body, RouteConstraints(mode="cascade"))
        self.assertTrue(response["choices"][0]["message"]["content"])
        self.assertGreaterEqual(len(self.provider.calls), 2)

    def test_draft_verify_calls_two_models(self):
        body = basic_body("Analyze this architecture in detail and verify it")
        response, _ = self.service.chat(body, RouteConstraints(mode="draft_verify"))
        self.assertEqual(response["rooomtech_route"]["topology"], "draft_verify")
        self.assertEqual(len(self.provider.calls), 2)

    def test_consensus_calls_workers_and_synthesizer(self):
        body = basic_body("Research all evidence, compare it, and verify every step")
        response, _ = self.service.chat(
            body, RouteConstraints(mode="parallel_consensus", high_stakes=True)
        )
        self.assertEqual(response["rooomtech_route"]["topology"], "parallel_consensus")
        self.assertGreaterEqual(len(self.provider.calls), 3)

    def test_receipt_does_not_store_prompt(self):
        secret_prompt = "DO_NOT_PERSIST_THIS_PROMPT_7b9c"
        response, _ = self.service.chat(basic_body(secret_prompt), RouteConstraints())
        route = self.store.get_route(response["rooomtech_route"]["id"])
        self.assertNotIn(secret_prompt, str(route["receipt"]))
        self.assertNotIn(secret_prompt, str(route["plan"]))

    def test_signed_receipt(self):
        os.environ["ROOOMTECH_RECEIPT_SECRET"] = "test-secret"
        try:
            response, _ = self.service.chat(basic_body(), RouteConstraints())
        finally:
            os.environ.pop("ROOOMTECH_RECEIPT_SECRET", None)
        self.assertTrue(response["rooomtech_route"]["receipt_signature"].startswith("sha256="))

    def test_feedback_updates_learning_stats(self):
        response, _ = self.service.chat(basic_body("hello"), RouteConstraints())
        route_id = response["rooomtech_route"]["id"]
        result = self.service.feedback(route_id, 0.9, category="user_rating")
        model_id = result["updated_models"][0]
        stats = self.store.model_stats(model_id, "general")
        self.assertEqual(stats["feedback_trials"], 1)
        self.assertAlmostEqual(stats["reward_sum"], 0.9)


if __name__ == "__main__":
    unittest.main()

