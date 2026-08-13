#!/usr/bin/env python3
"""Deterministic regression suite for policy and route-planning behavior."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rooomtech_router.config import load_config
from rooomtech_router.planner import RoutePlanner
from rooomtech_router.schemas import RouteConstraints
from rooomtech_router.store import RouterStore


def constraints(raw: dict) -> RouteConstraints:
    routing = raw.get("routing", {})
    return RouteConstraints(
        tenant_id=routing.get("tenant_id", "default"),
        data_class=routing.get("data_class", "public"),
        region=routing.get("region"),
        max_cost_usd=routing.get("max_cost_usd"),
        max_latency_ms=routing.get("max_latency_ms"),
        min_quality=routing.get("min_quality"),
        mode=routing.get("mode", "auto"),
        high_stakes=bool(routing.get("high_stakes", False)),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--cases", default=str(Path(__file__).with_name("policy_cases.jsonl"))
    )
    args = parser.parse_args()
    config = load_config(args.config)
    store = RouterStore(":memory:")
    planner = RoutePlanner(config, store)
    results = []
    failed = 0
    for line in Path(args.cases).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        body = {
            "model": "rooomtech-auto",
            "messages": [{"role": "user", "content": case["prompt"]}],
            "max_tokens": 1024,
        }
        if case.get("tools"):
            body["tools"] = case["tools"]
        plan = planner.plan(body, body["messages"], constraints(case))
        errors = []
        expected_topology = case.get("expected_topology")
        if expected_topology and plan.topology != expected_topology:
            errors.append(f"topology={plan.topology}, expected={expected_topology}")
        allowed = set(case.get("allowed_models", []))
        if allowed and not set(plan.selected_models).issubset(allowed):
            errors.append(f"models={list(plan.selected_models)}, allowed={sorted(allowed)}")
        expected_class = case.get("expected_data_class")
        if expected_class and plan.task.detected_data_class != expected_class:
            errors.append(
                f"data_class={plan.task.detected_data_class}, expected={expected_class}"
            )
        minimum_diversity = int(case.get("min_provider_diversity", 0))
        providers = {config.model(model_id).provider for model_id in plan.selected_models}
        if minimum_diversity and len(providers) < minimum_diversity:
            errors.append(
                f"provider_diversity={len(providers)}, expected>={minimum_diversity}"
            )
        passed = not errors
        failed += int(not passed)
        results.append(
            {
                "id": case["id"],
                "passed": passed,
                "topology": plan.topology,
                "models": list(plan.selected_models),
                "errors": errors,
            }
        )
    store.close()
    print(json.dumps({"passed": len(results) - failed, "failed": failed, "cases": results}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

