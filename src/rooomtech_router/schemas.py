"""Internal immutable request, plan, and execution records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RouteConstraints:
    tenant_id: str = "default"
    data_class: str = "public"
    region: str | None = None
    max_cost_usd: float | None = None
    max_latency_ms: int | None = None
    min_quality: float | None = None
    mode: str = "auto"
    required_capabilities: tuple[str, ...] = ()
    high_stakes: bool = False
    explain: bool = True
    forced_model: str | None = None


@dataclass(frozen=True, slots=True)
class TaskProfile:
    task_type: str
    complexity: float
    input_tokens: int
    expected_output_tokens: int
    required_capabilities: tuple[str, ...]
    detected_data_class: str
    high_stakes: bool


@dataclass(frozen=True, slots=True)
class ModelScore:
    model_id: str
    score: float
    predicted_quality: float
    reliability: float
    estimated_cost_usd: float
    estimated_latency_ms: int
    exploration_bonus: float
    factors: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "score": round(self.score, 6),
            "predicted_quality": round(self.predicted_quality, 6),
            "reliability": round(self.reliability, 6),
            "estimated_cost_usd": round(self.estimated_cost_usd, 8),
            "estimated_latency_ms": self.estimated_latency_ms,
            "exploration_bonus": round(self.exploration_bonus, 6),
            "factors": {key: round(value, 6) for key, value in self.factors.items()},
        }


@dataclass(frozen=True, slots=True)
class RoutePlan:
    task: TaskProfile
    topology: str
    selected_models: tuple[str, ...]
    synthesizer_model: str | None
    scores: tuple[ModelScore, ...]
    rejected: dict[str, tuple[str, ...]]
    estimated_cost_usd: float
    estimated_latency_ms: int
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": {
                "type": self.task.task_type,
                "complexity": round(self.task.complexity, 4),
                "input_tokens": self.task.input_tokens,
                "expected_output_tokens": self.task.expected_output_tokens,
                "required_capabilities": list(self.task.required_capabilities),
                "detected_data_class": self.task.detected_data_class,
                "high_stakes": self.task.high_stakes,
            },
            "topology": self.topology,
            "selected_models": list(self.selected_models),
            "synthesizer_model": self.synthesizer_model,
            "scores": [score.as_dict() for score in self.scores],
            "rejected": {key: list(value) for key, value in self.rejected.items()},
            "estimated_cost_usd": round(self.estimated_cost_usd, 8),
            "estimated_latency_ms": self.estimated_latency_ms,
            "reasons": list(self.reasons),
        }


@dataclass(slots=True)
class ProviderCall:
    model_id: str
    role: str
    status: str
    duration_ms: int
    response: dict[str, Any] | None = None
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def receipt_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "role": self.role,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 8),
            "error": self.error,
        }

