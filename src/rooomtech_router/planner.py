"""Explainable, multi-objective route planning with online feedback priors."""

from __future__ import annotations

import math
import re
from typing import Any

from .config import DATA_CLASSES, ModelConfig, RouterConfig, TenantPolicy
from .errors import BudgetExceededError, NoEligibleModelError, PolicyDeniedError
from .policy import (
    class_rank,
    detect_capabilities,
    detect_data_class,
    estimate_tokens,
    max_class,
    message_text,
)
from .schemas import ModelScore, RouteConstraints, RoutePlan, TaskProfile
from .store import RouterStore


_TASK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("code", re.compile(r"(?i)\b(code|bug|function|class|repository|git|sql|python|javascript)\b|(?:実装|コード|バグ|修正|リポジトリ)")),
    ("math", re.compile(r"(?i)\b(equation|proof|calculate|integral|theorem)\b|(?:数式|証明|計算|方程式)")),
    ("research", re.compile(r"(?i)\b(research|compare|sources?|evidence|paper)\b|(?:調査|比較|出典|論文|根拠)")),
    ("legal", re.compile(r"(?i)\b(law|legal|contract|regulation)\b|(?:判例|法律|契約|規則|法令)")),
    ("medical", re.compile(r"(?i)\b(medical|diagnosis|treatment|patient)\b|(?:診断|治療|患者|病気|薬)")),
    ("finance", re.compile(r"(?i)\b(financial|investment|loan|tax)\b|(?:投資|融資|税金|ローン|会計)")),
    ("extraction", re.compile(r"(?i)\b(extract|classify|json|schema)\b|(?:抽出|分類|構造化)")),
)

_COMPLEXITY_MARKERS = re.compile(
    r"(?i)\b(step[- ]?by[- ]?step|multi[- ]?step|analy[sz]e|verify|architecture)\b|"
    r"(?:徹底|詳細|複数|検証|設計|アーキテクチャ|段階|すべて|全部)"
)


class RoutePlanner:
    MODES = {"auto", "direct", "cascade", "draft_verify", "parallel_consensus"}

    def __init__(self, config: RouterConfig, store: RouterStore) -> None:
        self.config = config
        self.store = store

    def profile(
        self,
        body: dict[str, Any],
        messages: list[dict[str, Any]],
        constraints: RouteConstraints,
    ) -> TaskProfile:
        text = message_text(messages)
        task_type = "general"
        for name, pattern in _TASK_PATTERNS:
            if pattern.search(text):
                task_type = name
                break
        input_tokens = estimate_tokens(messages)
        requested_output = body.get("max_completion_tokens", body.get("max_tokens", 1024))
        try:
            expected_output = max(64, min(131_072, int(requested_output)))
        except (TypeError, ValueError):
            expected_output = 1024
        markers = len(_COMPLEXITY_MARKERS.findall(text))
        length_factor = min(0.45, input_tokens / 24_000)
        marker_factor = min(0.35, markers * 0.08)
        structure_factor = min(0.20, (text.count("\n") + text.count("?") - 1) * 0.02)
        complexity = min(1.0, max(0.05, 0.10 + length_factor + marker_factor + structure_factor))
        capabilities = set(detect_capabilities(body, messages))
        capabilities.update(constraints.required_capabilities)
        detected_class, _ = (
            detect_data_class(text)
            if self.config.runtime.auto_classify_sensitive_data
            else ("public", ())
        )
        effective_class = max_class(constraints.data_class, detected_class)
        high_stakes = constraints.high_stakes or task_type in {"legal", "medical", "finance"}
        if high_stakes:
            complexity = max(complexity, 0.70)
        return TaskProfile(
            task_type=task_type,
            complexity=round(complexity, 4),
            input_tokens=input_tokens,
            expected_output_tokens=expected_output,
            required_capabilities=tuple(sorted(capabilities)),
            detected_data_class=effective_class,
            high_stakes=high_stakes,
        )

    def plan(
        self,
        body: dict[str, Any],
        messages: list[dict[str, Any]],
        constraints: RouteConstraints,
    ) -> RoutePlan:
        if constraints.mode not in self.MODES:
            raise PolicyDeniedError(
                f"Unsupported routing mode: {constraints.mode}",
                details={"allowed_modes": sorted(self.MODES)},
            )
        tenant = self.config.tenant(constraints.tenant_id)
        task = self.profile(body, messages, constraints)
        if class_rank(task.detected_data_class) > class_rank(tenant.max_data_class):
            raise PolicyDeniedError(
                "The request data class exceeds the tenant policy",
                details={
                    "request_data_class": task.detected_data_class,
                    "tenant_max_data_class": tenant.max_data_class,
                },
            )
        max_cost = (
            tenant.default_max_cost_usd
            if constraints.max_cost_usd is None
            else max(0.0, constraints.max_cost_usd)
        )
        max_latency = (
            tenant.default_max_latency_ms
            if constraints.max_latency_ms is None
            else max(1, constraints.max_latency_ms)
        )
        min_quality = tenant.min_quality if constraints.min_quality is None else constraints.min_quality
        scores: list[ModelScore] = []
        rejected: dict[str, tuple[str, ...]] = {}
        total_trials = self.store.total_feedback_trials(task.task_type)
        for model in self.config.models:
            reasons = self._rejection_reasons(
                model, tenant, task, constraints, max_cost, max_latency
            )
            if reasons:
                rejected[model.id] = tuple(reasons)
                continue
            score = self._score_model(
                model,
                tenant,
                task,
                max_cost=max_cost,
                max_latency=max_latency,
                total_trials=total_trials,
            )
            if score.predicted_quality < min_quality:
                rejected[model.id] = (
                    f"predicted_quality_below_minimum:{score.predicted_quality:.3f}<{min_quality:.3f}",
                )
                continue
            scores.append(score)
        scores.sort(key=lambda item: (-item.score, item.estimated_cost_usd, item.model_id))

        if constraints.forced_model:
            forced = next((item for item in scores if item.model_id == constraints.forced_model), None)
            if forced is None:
                raise NoEligibleModelError(
                    f"Forced model is not eligible: {constraints.forced_model}",
                    details={"reasons": list(rejected.get(constraints.forced_model, ("unknown_model",)))},
                )
            scores = [forced] + [item for item in scores if item.model_id != forced.model_id]
        if not scores:
            raise NoEligibleModelError(
                "No model satisfies policy, capability, cost, and latency constraints",
                details={"rejected": {key: list(value) for key, value in rejected.items()}},
            )

        topology, selected, synthesizer, reasons = self._choose_topology(
            task, scores, constraints, max_cost
        )
        selected_scores = [self._score_by_id(scores, model_id) for model_id in selected]
        synth_score = self._score_by_id(scores, synthesizer) if synthesizer else None
        if topology == "parallel_consensus":
            estimated_cost = sum(item.estimated_cost_usd for item in selected_scores)
            estimated_cost += (synth_score.estimated_cost_usd * 1.5) if synth_score else 0
            estimated_latency = max(item.estimated_latency_ms for item in selected_scores)
            estimated_latency += synth_score.estimated_latency_ms if synth_score else 0
        elif topology == "draft_verify":
            estimated_cost = sum(item.estimated_cost_usd for item in selected_scores)
            estimated_latency = sum(item.estimated_latency_ms for item in selected_scores)
        else:
            estimated_cost = selected_scores[0].estimated_cost_usd
            estimated_latency = selected_scores[0].estimated_latency_ms

        if estimated_cost > max_cost + 1e-12:
            top = scores[0]
            if top.estimated_cost_usd > max_cost + 1e-12:
                raise BudgetExceededError(
                    "No eligible route fits the request budget",
                    details={
                        "max_cost_usd": max_cost,
                        "least_route_cost_usd": top.estimated_cost_usd,
                    },
                )
            topology, selected, synthesizer = "direct", (top.model_id,), None
            estimated_cost, estimated_latency = top.estimated_cost_usd, top.estimated_latency_ms
            reasons.append("degraded_to_direct_to_respect_hard_cost_budget")

        return RoutePlan(
            task=task,
            topology=topology,
            selected_models=tuple(selected),
            synthesizer_model=synthesizer,
            scores=tuple(scores),
            rejected=rejected,
            estimated_cost_usd=estimated_cost,
            estimated_latency_ms=estimated_latency,
            reasons=tuple(reasons),
        )

    def _rejection_reasons(
        self,
        model: ModelConfig,
        tenant: TenantPolicy,
        task: TaskProfile,
        constraints: RouteConstraints,
        max_cost: float,
        max_latency: int,
    ) -> list[str]:
        reasons: list[str] = []
        if not model.enabled:
            reasons.append("disabled")
        if "*" not in tenant.allowed_providers and model.provider not in tenant.allowed_providers:
            reasons.append("provider_not_allowed")
        if model.deployment not in tenant.allowed_deployments:
            reasons.append("deployment_not_allowed")
        if class_rank(task.detected_data_class) > class_rank(model.max_data_class):
            reasons.append(
                f"data_class_exceeds_model_policy:{task.detected_data_class}>{model.max_data_class}"
            )
        if constraints.region:
            if (
                "*" not in tenant.allowed_regions
                and constraints.region not in tenant.allowed_regions
            ):
                reasons.append("request_region_not_allowed_for_tenant")
            if "global" not in model.regions and constraints.region not in model.regions:
                reasons.append("model_not_available_in_region")
        missing_caps = sorted(set(task.required_capabilities) - set(model.capabilities))
        if missing_caps:
            reasons.append(f"missing_capabilities:{','.join(missing_caps)}")
        if task.input_tokens + task.expected_output_tokens > model.context_window:
            reasons.append("context_window_exceeded")
        if task.expected_output_tokens > model.max_output_tokens:
            reasons.append("max_output_tokens_exceeded")
        cost = self._estimate_cost(model, task)
        if cost > max_cost + 1e-12:
            reasons.append(f"estimated_cost_exceeds_budget:{cost:.8f}>{max_cost:.8f}")
        if model.latency_ms > max_latency:
            reasons.append(f"latency_exceeds_slo:{model.latency_ms}>{max_latency}")
        return reasons

    @staticmethod
    def _estimate_cost(model: ModelConfig, task: TaskProfile) -> float:
        return (
            task.input_tokens * model.input_cost_per_million
            + task.expected_output_tokens * model.output_cost_per_million
        ) / 1_000_000

    def _score_model(
        self,
        model: ModelConfig,
        tenant: TenantPolicy,
        task: TaskProfile,
        *,
        max_cost: float,
        max_latency: int,
        total_trials: int,
    ) -> ModelScore:
        stats = self.store.model_stats(model.id, task.task_type)
        prior = model.quality_for(task.task_type)
        prior_strength = 4.0
        trials = stats["feedback_trials"]
        quality = (prior_strength * prior + stats["reward_sum"]) / (prior_strength + trials)
        calls = stats["success_calls"] + stats["failure_calls"]
        reliability = (9.0 + stats["success_calls"]) / (10.0 + calls)
        observed_latency = stats["latency_ewma"] or float(model.latency_ms)
        estimated_cost = self._estimate_cost(model, task)
        cost_factor = 1.0 if estimated_cost == 0 else max(0.0, 1.0 - estimated_cost / max(max_cost, 1e-9))
        latency_factor = max(0.0, 1.0 - observed_latency / max(float(max_latency), 1.0))
        privacy_factor = 1.0 if model.deployment == "local" else 0.60
        exploration = min(
            0.12,
            math.sqrt(math.log(total_trials + 2.0) / (trials + 1.0)) * 0.04,
        )
        factors = {
            "quality": quality,
            "reliability": reliability,
            "cost": cost_factor,
            "latency": latency_factor,
            "privacy": privacy_factor,
        }
        weighted = sum(tenant.weights[key] * factors[key] for key in tenant.weights)
        score = min(1.0, max(0.0, weighted + exploration))
        return ModelScore(
            model_id=model.id,
            score=score,
            predicted_quality=quality,
            reliability=reliability,
            estimated_cost_usd=estimated_cost,
            estimated_latency_ms=int(observed_latency),
            exploration_bonus=exploration,
            factors=factors,
        )

    def _choose_topology(
        self,
        task: TaskProfile,
        scores: list[ModelScore],
        constraints: RouteConstraints,
        max_cost: float,
    ) -> tuple[str, tuple[str, ...], str | None, list[str]]:
        reasons: list[str] = []
        mode = constraints.mode
        if "tools" in task.required_capabilities and mode == "auto":
            mode = "cascade"
            reasons.append("tool_calling_kept_on_one_agent_per_turn")
        elif mode == "auto":
            if task.high_stakes or task.complexity >= 0.80:
                mode = "parallel_consensus"
                reasons.append("high_stakes_or_high_complexity_requires_independent_answers")
            elif task.complexity >= 0.50:
                mode = "draft_verify"
                reasons.append("medium_complexity_uses_independent_verification")
            else:
                mode = "direct"
                reasons.append("simple_request_uses_low_latency_direct_route")

        if constraints.forced_model:
            mode = "direct"
            reasons.append("caller_forced_a_specific_model")

        if mode == "direct":
            return "direct", (scores[0].model_id,), None, reasons
        if mode == "cascade":
            reasons.append("ordered_failover_is_enabled")
            return "cascade", tuple(item.model_id for item in scores), None, reasons

        if len(scores) < 2:
            reasons.append("only_one_eligible_model_so_topology_degraded_to_direct")
            return "direct", (scores[0].model_id,), None, reasons

        diverse: list[ModelScore] = [scores[0]]
        providers = {self.config.model(scores[0].model_id).provider}
        for candidate in scores[1:]:
            provider = self.config.model(candidate.model_id).provider
            if provider not in providers:
                diverse.append(candidate)
                providers.add(provider)
            if len(diverse) >= min(self.config.runtime.max_parallel, 3):
                break
        if len(diverse) < 2:
            diverse.append(scores[1])
            reasons.append("provider_diversity_unavailable_model_diversity_used")
        else:
            reasons.append("selected_models_span_independent_providers")

        if mode == "draft_verify":
            selected = (diverse[0].model_id, diverse[1].model_id)
            return "draft_verify", selected, None, reasons

        workers = tuple(item.model_id for item in diverse)
        synthesizer = scores[0].model_id
        estimated = sum(item.estimated_cost_usd for item in diverse)
        estimated += scores[0].estimated_cost_usd * 1.5
        if estimated > max_cost:
            reasons.append("consensus_estimate_exceeded_budget_using_draft_verify")
            return "draft_verify", (diverse[0].model_id, diverse[1].model_id), None, reasons
        return "parallel_consensus", workers, synthesizer, reasons

    @staticmethod
    def _score_by_id(scores: list[ModelScore], model_id: str | None) -> ModelScore:
        for score in scores:
            if score.model_id == model_id:
                return score
        raise KeyError(model_id)
