import unittest

from rooomtech_router.errors import NoEligibleModelError
from rooomtech_router.planner import RoutePlanner
from rooomtech_router.schemas import RouteConstraints
from rooomtech_router.store import RouterStore

from tests.helpers import basic_body, make_config


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.store = RouterStore(":memory:")
        self.planner = RoutePlanner(self.config, self.store)

    def tearDown(self):
        self.store.close()

    def test_simple_request_routes_direct(self):
        body = basic_body("Say hello")
        plan = self.planner.plan(body, body["messages"], RouteConstraints())
        self.assertEqual(plan.topology, "direct")
        self.assertEqual(len(plan.selected_models), 1)

    def test_complex_research_uses_diverse_consensus(self):
        body = basic_body(
            "Research and compare all evidence in multiple steps. Verify every source and analyze the architecture."
        )
        plan = self.planner.plan(body, body["messages"], RouteConstraints(high_stakes=True))
        self.assertEqual(plan.topology, "parallel_consensus")
        providers = {self.config.model(model_id).provider for model_id in plan.selected_models}
        self.assertGreaterEqual(len(providers), 2)

    def test_restricted_data_stays_local(self):
        body = basic_body("Use this api_key = sk-abcdefghijklmnopqrstuvwxyz1234")
        plan = self.planner.plan(body, body["messages"], RouteConstraints())
        self.assertEqual(plan.selected_models, ("local-general",))
        self.assertIn("cloud-code", plan.rejected)

    def test_tools_use_cascade(self):
        body = basic_body(
            "Use a tool",
            tools=[{"type": "function", "function": {"name": "lookup", "parameters": {}}}],
        )
        plan = self.planner.plan(body, body["messages"], RouteConstraints())
        self.assertEqual(plan.topology, "cascade")

    def test_forced_ineligible_model_is_denied(self):
        body = basic_body("password=secret-value")
        with self.assertRaises(NoEligibleModelError):
            self.planner.plan(
                body,
                body["messages"],
                RouteConstraints(forced_model="cloud-code"),
            )

    def test_local_only_tenant(self):
        body = basic_body("Analyze architecture thoroughly")
        plan = self.planner.plan(
            body,
            body["messages"],
            RouteConstraints(tenant_id="local-only", region="JP"),
        )
        self.assertEqual(plan.selected_models, ("local-general",))


if __name__ == "__main__":
    unittest.main()

