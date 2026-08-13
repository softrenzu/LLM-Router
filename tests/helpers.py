from __future__ import annotations

import time
import uuid
from typing import Any

from rooomtech_router.config import RouterConfig


def make_config(*, require_auth: bool = False, database_path: str = ":memory:") -> RouterConfig:
    return RouterConfig.from_dict(
        {
            "router": {
                "database_path": database_path,
                "max_parallel": 3,
                "require_auth": require_auth,
                "cache_ttl_seconds": 0,
            },
            "tenants": {
                "default": {
                    "allowed_providers": ["*"],
                    "allowed_deployments": ["local", "cloud"],
                    "allowed_regions": ["*"],
                    "max_data_class": "restricted",
                    "default_max_cost_usd": 1.0,
                    "default_max_latency_ms": 120000,
                },
                "local-only": {
                    "allowed_providers": ["local"],
                    "allowed_deployments": ["local"],
                    "allowed_regions": ["JP"],
                    "max_data_class": "restricted",
                    "default_max_cost_usd": 0.0,
                    "default_max_latency_ms": 120000,
                },
            },
            "models": [
                {
                    "id": "local-general",
                    "provider": "local",
                    "base_url": "http://local/v1",
                    "model": "local-general",
                    "deployment": "local",
                    "regions": ["JP"],
                    "capabilities": ["chat", "tools", "json", "reasoning", "code"],
                    "max_data_class": "restricted",
                    "input_cost_per_million": 0,
                    "output_cost_per_million": 0,
                    "latency_ms": 1500,
                    "quality": {"general": 0.72, "code": 0.76, "research": 0.70},
                },
                {
                    "id": "cloud-code",
                    "provider": "cloud-a",
                    "base_url": "http://cloud-a/v1",
                    "model": "cloud-code",
                    "deployment": "cloud",
                    "regions": ["global", "JP"],
                    "capabilities": ["chat", "tools", "json", "reasoning", "code"],
                    "max_data_class": "internal",
                    "input_cost_per_million": 2,
                    "output_cost_per_million": 10,
                    "latency_ms": 2200,
                    "quality": {"general": 0.84, "code": 0.95, "research": 0.82},
                },
                {
                    "id": "cloud-research",
                    "provider": "cloud-b",
                    "base_url": "http://cloud-b/v1",
                    "model": "cloud-research",
                    "deployment": "cloud",
                    "regions": ["global", "JP"],
                    "capabilities": ["chat", "json", "reasoning", "vision"],
                    "max_data_class": "internal",
                    "input_cost_per_million": 3,
                    "output_cost_per_million": 15,
                    "latency_ms": 3000,
                    "quality": {
                        "general": 0.88,
                        "research": 0.96,
                        "math": 0.93,
                        "legal": 0.88,
                        "medical": 0.88,
                        "finance": 0.86
                    },
                },
            ],
        }
    )


class FakeProvider:
    def __init__(self, failures: set[str] | None = None) -> None:
        self.failures = failures or set()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def chat(self, model, payload, *, timeout):
        self.calls.append((model.id, payload))
        if model.id in self.failures:
            raise RuntimeError(f"planned failure for {model.id}")
        last = ""
        for message in reversed(payload.get("messages", [])):
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                last = message["content"]
                break
        content = f"{model.id}:{last[:80]}"
        return {
            "id": f"chatcmpl-fake-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        }


def basic_body(text: str = "Hello", **overrides: Any) -> dict[str, Any]:
    body = {
        "model": "rooomtech-auto",
        "messages": [{"role": "user", "content": text}],
        "max_tokens": 512,
        "temperature": 0,
    }
    body.update(overrides)
    return body

