#!/usr/bin/env python3
"""Tiny OpenAI-compatible mock endpoint for the quick-start and integration tests."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def estimate(value: Any) -> int:
    return max(1, len(json.dumps(value, ensure_ascii=False)) // 4)


class MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._json(HTTPStatus.OK, {"status": "ok", "provider": self.server.name})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        messages = body.get("messages", [])
        last_text = ""
        for message in reversed(messages):
            if message.get("role") == "user" and isinstance(message.get("content"), str):
                last_text = message["content"]
                break
        text = f"[{self.server.name}] processed: {last_text[:240]}"
        response = {
            "id": f"chatcmpl-mock-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", self.server.name),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": estimate(messages),
                "completion_tokens": estimate(text),
                "total_tokens": estimate(messages) + estimate(text),
            },
        }
        self._json(HTTPStatus.OK, response)

    def _json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format_: str, *args: Any) -> None:
        return


class MockServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], name: str) -> None:
        super().__init__(address, MockHandler)
        self.name = name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    server = MockServer(("0.0.0.0", args.port), args.name)
    print(f"Mock provider {args.name} listening on {args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

