"""Dependency-free OpenAI-compatible HTTP server."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .config import DATA_CLASSES, RouterConfig, load_config
from .errors import (
    AuthenticationError,
    ConfigurationError,
    InvalidRequestError,
    RouterError,
)
from .orchestrator import RouterService
from .schemas import RouteConstraints


MAX_BODY_BYTES = 10 * 1024 * 1024


def _boolean(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _optional_float(value: Any, name: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError(f"{name} must be a number") from exc
    if parsed < 0:
        raise InvalidRequestError(f"{name} must not be negative")
    return parsed


def _optional_int(value: Any, name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise InvalidRequestError(f"{name} must be positive")
    return parsed


class RouterHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        service: RouterService,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.service = service
        raw_keys = os.environ.get(service.config.runtime.api_keys_env, "")
        self.api_keys = tuple(key.strip() for key in raw_keys.split(",") if key.strip())
        if service.config.runtime.require_auth and not self.api_keys:
            raise ConfigurationError(
                f"Authentication is required but {service.config.runtime.api_keys_env} is empty"
            )


class RouterHandler(BaseHTTPRequestHandler):
    server: RouterHTTPServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        try:
            path = urlparse(self.path).path
            if path in {"/healthz", "/v1/health"}:
                self._json(HTTPStatus.OK, {"status": "ok", "version": "0.1.0"})
                return
            if path == "/readyz":
                self._json(
                    HTTPStatus.OK,
                    {
                        "status": "ready",
                        "configured_models": len(self.server.service.config.models),
                        "circuits": self.server.service.circuit.snapshot(),
                    },
                )
                return
            if path == "/metrics":
                self._require_auth()
                payload = self.server.service.metrics.render().encode("utf-8")
                self._bytes(HTTPStatus.OK, payload, "text/plain; version=0.0.4; charset=utf-8")
                return
            if path == "/v1/models":
                self._require_auth()
                self._json(HTTPStatus.OK, self._models_response())
                return
            if path.startswith("/v1/routes/"):
                self._require_auth()
                route_id = path.removeprefix("/v1/routes/").strip("/")
                route = self.server.service.store.get_route(route_id)
                if route is None:
                    raise InvalidRequestError(f"Unknown route_id: {route_id}")
                self._json(HTTPStatus.OK, route)
                return
            self._json(
                HTTPStatus.NOT_FOUND,
                {"error": {"message": "Not found", "type": "not_found", "code": "not_found"}},
            )
        except RouterError as exc:
            self._router_error(exc)
        except Exception:
            self._router_error(RouterError("Internal server error"))

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        try:
            self._require_auth()
            path = urlparse(self.path).path
            body = self._read_json()
            if path == "/v1/chat/completions":
                constraints = self._constraints(body)
                stream = bool(body.get("stream", False))
                response, headers = self.server.service.chat(body, constraints)
                if stream:
                    self._chat_stream(response, headers)
                else:
                    self._json(HTTPStatus.OK, response, headers=headers)
                return
            if path == "/v1/responses":
                chat_body = self._responses_to_chat(body)
                constraints = self._constraints(chat_body)
                stream = bool(body.get("stream", False))
                chat_response, headers = self.server.service.chat(chat_body, constraints)
                response = self._chat_to_responses(chat_response)
                if stream:
                    self._responses_stream(response, headers)
                else:
                    self._json(HTTPStatus.OK, response, headers=headers)
                return
            if path == "/v1/route/plan":
                constraints = self._constraints(body)
                self._json(HTTPStatus.OK, self.server.service.plan(body, constraints))
                return
            if path == "/v1/feedback":
                route_id = body.get("route_id")
                if not isinstance(route_id, str) or not route_id:
                    raise InvalidRequestError("route_id is required")
                if "reward" not in body:
                    raise InvalidRequestError("reward is required")
                try:
                    reward = float(body["reward"])
                except (TypeError, ValueError) as exc:
                    raise InvalidRequestError("reward must be a number between 0 and 1") from exc
                if not 0 <= reward <= 1:
                    raise InvalidRequestError("reward must be between 0 and 1")
                result = self.server.service.feedback(
                    route_id,
                    reward,
                    model_id=body.get("model_id"),
                    category=body.get("category"),
                )
                self._json(HTTPStatus.ACCEPTED, result)
                return
            self._json(
                HTTPStatus.NOT_FOUND,
                {"error": {"message": "Not found", "type": "not_found", "code": "not_found"}},
            )
        except RouterError as exc:
            self._router_error(exc)
        except Exception:
            self._router_error(RouterError("Internal server error"))

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler API
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _constraints(self, body: dict[str, Any]) -> RouteConstraints:
        routing_raw = body.get("routing", {})
        if routing_raw is None:
            routing_raw = {}
        if not isinstance(routing_raw, dict):
            raise InvalidRequestError("routing must be an object")
        tenant_id = str(
            routing_raw.get("tenant_id")
            or self.headers.get("X-Rooomtech-Tenant")
            or "default"
        )
        data_class = str(
            routing_raw.get("data_class")
            or self.headers.get("X-Rooomtech-Data-Class")
            or "public"
        ).lower()
        if data_class not in DATA_CLASSES:
            raise InvalidRequestError(
                f"data_class must be one of: {', '.join(DATA_CLASSES)}"
            )
        mode = str(
            routing_raw.get("mode")
            or self.headers.get("X-Rooomtech-Mode")
            or "auto"
        )
        requested_model = body.get("model")
        aliases = {
            "rooomtech-auto": "auto",
            "rooomtech-direct": "direct",
            "rooomtech-consensus": "parallel_consensus",
            "rooomtech-verified": "draft_verify",
        }
        forced_model = None
        if isinstance(requested_model, str) and requested_model in aliases:
            if mode == "auto":
                mode = aliases[requested_model]
        elif isinstance(requested_model, str) and requested_model:
            forced_model = requested_model
        required = routing_raw.get("required_capabilities", ())
        if isinstance(required, str):
            required = (required,)
        if not isinstance(required, (list, tuple)):
            raise InvalidRequestError("required_capabilities must be an array")
        return RouteConstraints(
            tenant_id=tenant_id,
            data_class=data_class,
            region=routing_raw.get("region") or self.headers.get("X-Rooomtech-Region"),
            max_cost_usd=_optional_float(
                routing_raw.get("max_cost_usd", self.headers.get("X-Rooomtech-Max-Cost-USD")),
                "max_cost_usd",
            ),
            max_latency_ms=_optional_int(
                routing_raw.get(
                    "max_latency_ms", self.headers.get("X-Rooomtech-Max-Latency-Ms")
                ),
                "max_latency_ms",
            ),
            min_quality=_optional_float(routing_raw.get("min_quality"), "min_quality"),
            mode=mode,
            required_capabilities=tuple(str(item) for item in required),
            high_stakes=_boolean(routing_raw.get("high_stakes"), False),
            explain=_boolean(routing_raw.get("explain"), True),
            forced_model=forced_model,
        )

    def _require_auth(self) -> None:
        keys = self.server.api_keys
        if not keys:
            return
        authorization = self.headers.get("Authorization", "")
        supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
        if not supplied or not any(hmac.compare_digest(supplied, key) for key in keys):
            raise AuthenticationError("Invalid or missing router API key")

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise InvalidRequestError("Content-Length is required")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise InvalidRequestError("Invalid Content-Length") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise InvalidRequestError(f"Body must be between 1 and {MAX_BODY_BYTES} bytes")
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidRequestError("Request body must be valid UTF-8 JSON") from exc
        if not isinstance(parsed, dict):
            raise InvalidRequestError("Request body must be a JSON object")
        return parsed

    def _models_response(self) -> dict[str, Any]:
        created = int(time.time())
        aliases = [
            ("rooomtech-auto", "Adaptive multi-objective routing"),
            ("rooomtech-direct", "Lowest-overhead eligible model"),
            ("rooomtech-verified", "Draft plus independent verifier"),
            ("rooomtech-consensus", "Parallel independent answers plus synthesis"),
        ]
        return {
            "object": "list",
            "data": [
                {
                    "id": model_id,
                    "object": "model",
                    "created": created,
                    "owned_by": "rooomtech",
                    "description": description,
                }
                for model_id, description in aliases
            ],
        }

    @staticmethod
    def _responses_to_chat(body: dict[str, Any]) -> dict[str, Any]:
        input_value = body.get("input")
        messages: list[dict[str, Any]] = []
        instructions = body.get("instructions")
        if isinstance(instructions, str) and instructions:
            messages.append({"role": "system", "content": instructions})
        if isinstance(input_value, str):
            messages.append({"role": "user", "content": input_value})
        elif isinstance(input_value, list):
            for item in input_value:
                if isinstance(item, dict) and item.get("type") == "message":
                    messages.append(
                        {"role": item.get("role", "user"), "content": item.get("content", "")}
                    )
                elif isinstance(item, dict) and item.get("role"):
                    messages.append({"role": item["role"], "content": item.get("content", "")})
                elif isinstance(item, str):
                    messages.append({"role": "user", "content": item})
        if not messages:
            raise InvalidRequestError("input must contain at least one message")
        chat = {
            "model": body.get("model", "rooomtech-auto"),
            "messages": messages,
            "stream": body.get("stream", False),
        }
        mappings = {
            "max_output_tokens": "max_tokens",
            "temperature": "temperature",
            "top_p": "top_p",
            "tools": "tools",
            "tool_choice": "tool_choice",
            "routing": "routing",
        }
        for source, destination in mappings.items():
            if source in body:
                chat[destination] = body[source]
        return chat

    @staticmethod
    def _chat_to_responses(chat: dict[str, Any]) -> dict[str, Any]:
        choice = chat.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        usage = chat.get("usage", {})
        response = {
            "id": chat["id"].replace("chatcmpl-", "resp_", 1),
            "object": "response",
            "created_at": chat.get("created", int(time.time())),
            "status": "completed",
            "model": chat.get("model", "rooomtech-auto"),
            "output": [
                {
                    "id": f"msg_{chat['id'][-24:]}",
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": content, "annotations": []}
                    ],
                }
            ],
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            "error": None,
            "incomplete_details": None,
        }
        if "rooomtech_route" in chat:
            response["rooomtech_route"] = chat["rooomtech_route"]
        return response

    def _chat_stream(self, response: dict[str, Any], headers: dict[str, str]) -> None:
        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        self.send_response(HTTPStatus.OK)
        self._common_headers(headers)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        initial = self._chat_chunk(response, {"role": "assistant", "content": ""}, None)
        self._sse(initial)
        if message.get("tool_calls"):
            self._sse(self._chat_chunk(response, {"tool_calls": message["tool_calls"]}, None))
        elif isinstance(content, str):
            for start in range(0, len(content), 96):
                self._sse(self._chat_chunk(response, {"content": content[start : start + 96]}, None))
        self._sse(self._chat_chunk(response, {}, choice.get("finish_reason", "stop")))
        self._sse("[DONE]")
        self.close_connection = True

    @staticmethod
    def _chat_chunk(
        response: dict[str, Any], delta: dict[str, Any], finish_reason: str | None
    ) -> dict[str, Any]:
        chunk = {
            "id": response["id"],
            "object": "chat.completion.chunk",
            "created": response["created"],
            "model": response["model"],
            "system_fingerprint": response.get("system_fingerprint"),
            "choices": [
                {"index": 0, "delta": delta, "logprobs": None, "finish_reason": finish_reason}
            ],
        }
        if finish_reason is not None:
            chunk["usage"] = response.get("usage")
            chunk["rooomtech_route"] = response.get("rooomtech_route")
        return chunk

    def _responses_stream(self, response: dict[str, Any], headers: dict[str, str]) -> None:
        text = response["output"][0]["content"][0]["text"]
        self.send_response(HTTPStatus.OK)
        self._common_headers(headers)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self._sse({"type": "response.created", "response": {**response, "status": "in_progress"}})
        for start in range(0, len(text), 96):
            self._sse(
                {
                    "type": "response.output_text.delta",
                    "item_id": response["output"][0]["id"],
                    "output_index": 0,
                    "content_index": 0,
                    "delta": text[start : start + 96],
                }
            )
        self._sse({"type": "response.completed", "response": response})
        self._sse("[DONE]")
        self.close_connection = True

    def _sse(self, value: dict[str, Any] | str) -> None:
        data = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _json(
        self,
        status: int,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._bytes(status, payload, "application/json; charset=utf-8", headers=headers)

    def _bytes(
        self,
        status: int,
        payload: bytes,
        content_type: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self._common_headers(headers)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _common_headers(self, headers: dict[str, str] | None = None) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (headers or {}).items():
            self.send_header(key, value)

    def _router_error(self, error: RouterError) -> None:
        self.server.service.metrics.inc(
            "rooomtech_router_http_errors_total", code=error.code
        )
        self._json(error.status_code, error.as_openai_error())

    def log_message(self, format_: str, *args: Any) -> None:
        # Avoid logging request bodies or Authorization values. The path/status remain useful.
        sys.stderr.write(
            json.dumps(
                {
                    "time": self.log_date_time_string(),
                    "client": self.client_address[0],
                    "message": format_ % args,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def build_server(
    config: RouterConfig,
    *,
    host: str | None = None,
    port: int | None = None,
    service: RouterService | None = None,
) -> RouterHTTPServer:
    service = service or RouterService(config)
    return RouterHTTPServer(
        (host if host is not None else config.runtime.host, port if port is not None else config.runtime.port),
        RouterHandler,
        service,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rooomtech sovereign LLM router")
    parser.add_argument(
        "--config",
        default=os.environ.get("ROOOMTECH_ROUTER_CONFIG", "router.json"),
        help="Path to router JSON configuration",
    )
    parser.add_argument("--host", help="Override listen host")
    parser.add_argument("--port", type=int, help="Override listen port")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        server = build_server(config, host=args.host, port=args.port)
    except RouterError as exc:
        print(json.dumps(exc.as_openai_error(), ensure_ascii=False), file=sys.stderr)
        return 2
    host, port = server.server_address[:2]
    print(f"Rooomtech LLM Router listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
