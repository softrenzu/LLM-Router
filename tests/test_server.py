import json
import os
import threading
import unittest
import urllib.error
import urllib.request

from rooomtech_router.orchestrator import RouterService
from rooomtech_router.server import build_server
from rooomtech_router.store import RouterStore

from tests.helpers import FakeProvider, basic_body, make_config


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.store = RouterStore(":memory:")
        service = RouterService(self.config, store=self.store, provider=FakeProvider())
        self.server = build_server(self.config, host="127.0.0.1", port=0, service=service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.store.close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def post(self, path, body):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, dict(response.headers), json.loads(response.read().decode("utf-8"))

    def test_health_and_models(self):
        status, health = self.get("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(health["status"], "ok")
        status, models = self.get("/v1/models")
        self.assertEqual(status, 200)
        self.assertEqual(models["object"], "list")

    def test_chat_plan_feedback_and_route(self):
        status, _, plan = self.post("/v1/route/plan", basic_body("hello"))
        self.assertEqual(status, 200)
        self.assertIn("scores", plan)
        status, headers, chat = self.post("/v1/chat/completions", basic_body("hello"))
        self.assertEqual(status, 200)
        route_id = headers["X-Rooomtech-Route-Id"]
        status, _, feedback = self.post(
            "/v1/feedback", {"route_id": route_id, "reward": 1.0}
        )
        self.assertEqual(status, 202)
        self.assertTrue(feedback["accepted"])
        status, route = self.get(f"/v1/routes/{route_id}")
        self.assertEqual(status, 200)
        self.assertEqual(route["route_id"], route_id)

    def test_responses_api(self):
        status, _, response = self.post(
            "/v1/responses", {"model": "rooomtech-auto", "input": "hello"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["object"], "response")
        self.assertEqual(response["status"], "completed")

    def test_bearer_authentication(self):
        self.server.api_keys = ("router-secret",)
        request = urllib.request.Request(
            self.base + "/v1/chat/completions",
            data=json.dumps(basic_body()).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(context.exception.code, 401)
        request.add_header("Authorization", "Bearer router-secret")
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 200)

    def test_buffered_sse_is_protocol_compatible(self):
        body = basic_body("stream this", stream=True)
        request = urllib.request.Request(
            self.base + "/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = response.read().decode("utf-8")
        self.assertIn("chat.completion.chunk", payload)
        self.assertIn("data: [DONE]", payload)


if __name__ == "__main__":
    unittest.main()
