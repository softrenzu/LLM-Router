"""Strict JSON configuration with no runtime dependencies."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigurationError


DATA_CLASSES = ("public", "internal", "confidential", "restricted")


def _as_tuple(value: Any, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


@dataclass(frozen=True, slots=True)
class ModelConfig:
    id: str
    provider: str
    base_url: str
    model: str
    api_key_env: str | None = None
    deployment: str = "cloud"
    regions: tuple[str, ...] = ("global",)
    capabilities: tuple[str, ...] = ("chat",)
    context_window: int = 128_000
    max_output_tokens: int = 16_384
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0
    latency_ms: int = 2_000
    max_data_class: str = "internal"
    quality: dict[str, float] = field(default_factory=lambda: {"general": 0.70})
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ModelConfig":
        required = ("id", "provider", "base_url", "model")
        missing = [key for key in required if not raw.get(key)]
        if missing:
            raise ConfigurationError(f"Model configuration is missing: {', '.join(missing)}")
        data_class = str(raw.get("max_data_class", "internal"))
        if data_class not in DATA_CLASSES:
            raise ConfigurationError(
                f"Invalid max_data_class for {raw['id']}: {data_class}"
            )
        quality = {
            str(key): min(1.0, max(0.0, float(value)))
            for key, value in dict(raw.get("quality", {"general": 0.70})).items()
        }
        return cls(
            id=str(raw["id"]),
            provider=str(raw["provider"]),
            base_url=str(raw["base_url"]).rstrip("/"),
            model=str(raw["model"]),
            api_key_env=raw.get("api_key_env"),
            deployment=str(raw.get("deployment", "cloud")),
            regions=_as_tuple(raw.get("regions"), ("global",)),
            capabilities=_as_tuple(raw.get("capabilities"), ("chat",)),
            context_window=max(1, int(raw.get("context_window", 128_000))),
            max_output_tokens=max(1, int(raw.get("max_output_tokens", 16_384))),
            input_cost_per_million=max(0.0, float(raw.get("input_cost_per_million", 0))),
            output_cost_per_million=max(0.0, float(raw.get("output_cost_per_million", 0))),
            latency_ms=max(1, int(raw.get("latency_ms", 2_000))),
            max_data_class=data_class,
            quality=quality,
            headers={str(k): str(v) for k, v in dict(raw.get("headers", {})).items()},
            enabled=bool(raw.get("enabled", True)),
        )

    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) if self.api_key_env else None

    def quality_for(self, task_type: str) -> float:
        return self.quality.get(task_type, self.quality.get("general", 0.70))


@dataclass(frozen=True, slots=True)
class TenantPolicy:
    allowed_providers: tuple[str, ...] = ("*",)
    allowed_deployments: tuple[str, ...] = ("local", "cloud")
    allowed_regions: tuple[str, ...] = ("*",)
    max_data_class: str = "restricted"
    default_max_cost_usd: float = 1.0
    default_max_latency_ms: int = 120_000
    min_quality: float = 0.0
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "quality": 0.55,
            "reliability": 0.15,
            "cost": 0.10,
            "latency": 0.10,
            "privacy": 0.10,
        }
    )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TenantPolicy":
        data_class = str(raw.get("max_data_class", "restricted"))
        if data_class not in DATA_CLASSES:
            raise ConfigurationError(f"Invalid tenant max_data_class: {data_class}")
        weights = dict(raw.get("weights", {}))
        defaults = cls().weights
        normalized = {key: max(0.0, float(weights.get(key, value))) for key, value in defaults.items()}
        total = sum(normalized.values())
        if total <= 0:
            raise ConfigurationError("Tenant routing weights must have a positive sum")
        normalized = {key: value / total for key, value in normalized.items()}
        return cls(
            allowed_providers=_as_tuple(raw.get("allowed_providers"), ("*",)),
            allowed_deployments=_as_tuple(
                raw.get("allowed_deployments"), ("local", "cloud")
            ),
            allowed_regions=_as_tuple(raw.get("allowed_regions"), ("*",)),
            max_data_class=data_class,
            default_max_cost_usd=max(0.0, float(raw.get("default_max_cost_usd", 1.0))),
            default_max_latency_ms=max(1, int(raw.get("default_max_latency_ms", 120_000))),
            min_quality=min(1.0, max(0.0, float(raw.get("min_quality", 0.0)))),
            weights=normalized,
        )


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    database_path: str = "data/router.db"
    max_parallel: int = 3
    request_timeout_seconds: float = 120.0
    cache_ttl_seconds: int = 0
    circuit_breaker_failures: int = 3
    circuit_breaker_recovery_seconds: int = 30
    receipt_secret_env: str = "ROOOMTECH_RECEIPT_SECRET"
    api_keys_env: str = "ROOOMTECH_ROUTER_API_KEYS"
    require_auth: bool = False
    auto_classify_sensitive_data: bool = True
    expose_route_in_response: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RuntimeConfig":
        return cls(
            host=str(raw.get("host", "0.0.0.0")),
            port=int(raw.get("port", 8080)),
            database_path=str(raw.get("database_path", "data/router.db")),
            max_parallel=max(1, int(raw.get("max_parallel", 3))),
            request_timeout_seconds=max(1.0, float(raw.get("request_timeout_seconds", 120))),
            cache_ttl_seconds=max(0, int(raw.get("cache_ttl_seconds", 0))),
            circuit_breaker_failures=max(1, int(raw.get("circuit_breaker_failures", 3))),
            circuit_breaker_recovery_seconds=max(
                1, int(raw.get("circuit_breaker_recovery_seconds", 30))
            ),
            receipt_secret_env=str(
                raw.get("receipt_secret_env", "ROOOMTECH_RECEIPT_SECRET")
            ),
            api_keys_env=str(raw.get("api_keys_env", "ROOOMTECH_ROUTER_API_KEYS")),
            require_auth=bool(raw.get("require_auth", False)),
            auto_classify_sensitive_data=bool(
                raw.get("auto_classify_sensitive_data", True)
            ),
            expose_route_in_response=bool(raw.get("expose_route_in_response", True)),
        )


@dataclass(frozen=True, slots=True)
class RouterConfig:
    models: tuple[ModelConfig, ...]
    tenants: dict[str, TenantPolicy]
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RouterConfig":
        models = tuple(ModelConfig.from_dict(item) for item in raw.get("models", []))
        if not models:
            raise ConfigurationError("At least one model must be configured")
        identifiers = [model.id for model in models]
        duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
        if duplicates:
            raise ConfigurationError(f"Duplicate model ids: {', '.join(duplicates)}")
        tenants_raw = dict(raw.get("tenants", {"default": {}}))
        if "default" not in tenants_raw:
            tenants_raw["default"] = {}
        tenants = {
            str(name): TenantPolicy.from_dict(dict(policy))
            for name, policy in tenants_raw.items()
        }
        return cls(
            models=models,
            tenants=tenants,
            runtime=RuntimeConfig.from_dict(dict(raw.get("router", {}))),
        )

    def model(self, model_id: str) -> ModelConfig:
        for model in self.models:
            if model.id == model_id:
                return model
        raise ConfigurationError(f"Unknown model: {model_id}")

    def tenant(self, tenant_id: str) -> TenantPolicy:
        return self.tenants.get(tenant_id, self.tenants["default"])


def load_config(path: str | os.PathLike[str] | None = None) -> RouterConfig:
    config_path = Path(path or os.environ.get("ROOOMTECH_ROUTER_CONFIG", "router.json"))
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Configuration file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Invalid JSON in {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError("Configuration root must be an object")
    return RouterConfig.from_dict(raw)

