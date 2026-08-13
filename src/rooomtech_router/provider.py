"""Provider adapter for any OpenAI-compatible chat-completions endpoint."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Protocol

from .config import ModelConfig
from .errors import ProviderError


class Provider(Protocol):
    def chat(
        self, model: ModelConfig, payload: dict[str, Any], *, timeout: float
    ) -> dict[str, Any]: ...


class OpenAICompatibleProvider:
    """Dependency-free HTTP adapter used for OpenAI, vLLM, NIM, TGI, and Ollama."""

    user_agent = "rooomtech-llm-router/0.1.0"

    def chat(
        self, model: ModelConfig, payload: dict[str, Any], *, timeout: float
    ) -> dict[str, Any]:
        endpoint = f"{model.base_url}/chat/completions"
        body = dict(payload)
        body["model"] = model.model
        body["stream"] = False
        body.pop("routing", None)
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": self.user_agent,
            **model.headers,
        }
        api_key = model.api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(endpoint, data=encoded, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise ProviderError(
                f"Provider {model.id} returned HTTP {exc.code}",
                details={"model_id": model.id, "provider_status": exc.code, "body": detail},
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(
                f"Provider {model.id} is unavailable: {exc}",
                details={"model_id": model.id},
            ) from exc
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError(
                f"Provider {model.id} returned invalid JSON",
                details={"model_id": model.id},
            ) from exc
        if not isinstance(parsed, dict):
            raise ProviderError(f"Provider {model.id} returned a non-object response")
        if parsed.get("error"):
            raise ProviderError(
                f"Provider {model.id} returned an error",
                details={"model_id": model.id, "provider_error": parsed["error"]},
            )
        choices = parsed.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError(
                f"Provider {model.id} returned no choices",
                details={"model_id": model.id},
            )
        return parsed

