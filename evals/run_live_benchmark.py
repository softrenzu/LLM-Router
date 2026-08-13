#!/usr/bin/env python3
"""Run the same JSONL suite against any OpenAI-compatible endpoint.

This intentionally emits raw measurements instead of claiming benchmark superiority.
Use identical cases, model access, tool harness, timeout, and budget when comparing systems.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
import urllib.request
from pathlib import Path


def call(endpoint: str, model: str, prompt: str, timeout: float) -> tuple[dict, float]:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 2048,
    }
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("BENCHMARK_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    return parsed, (time.monotonic() - started) * 1000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--dataset", default=str(Path(__file__).with_name("live_cases.jsonl")))
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--output")
    args = parser.parse_args()
    rows = []
    for line in Path(args.dataset).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        response, latency_ms = call(args.endpoint, args.model, case["prompt"], args.timeout)
        text = response["choices"][0]["message"].get("content", "")
        terms = case.get("expected_terms", [])
        matched = [term for term in terms if term.lower() in text.lower()]
        rows.append(
            {
                "id": case["id"],
                "latency_ms": round(latency_ms, 2),
                "term_recall": len(matched) / len(terms) if terms else None,
                "usage": response.get("usage", {}),
                "route": response.get("rooomtech_route"),
            }
        )
    summary = {
        "endpoint": args.endpoint,
        "model": args.model,
        "cases": rows,
        "mean_latency_ms": round(statistics.mean(row["latency_ms"] for row in rows), 2),
        "mean_term_recall": round(
            statistics.mean(row["term_recall"] for row in rows if row["term_recall"] is not None),
            4,
        ),
    }
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

