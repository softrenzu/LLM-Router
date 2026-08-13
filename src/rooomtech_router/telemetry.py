"""Prometheus text metrics without importing a telemetry SDK."""

from __future__ import annotations

import threading
from collections import defaultdict


class Metrics:
    def __init__(self) -> None:
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = (name, tuple(sorted((str(k), str(v)) for k, v in labels.items())))
        with self._lock:
            self._counters[key] += value

    def render(self) -> str:
        with self._lock:
            items = sorted(self._counters.items())
        lines: list[str] = []
        declared: set[str] = set()
        for (name, labels), value in items:
            safe_name = name.replace("-", "_")
            if safe_name not in declared:
                lines.append(f"# TYPE {safe_name} counter")
                declared.add(safe_name)
            if labels:
                rendered_labels = ",".join(
                    f'{key}="{value_.replace(chr(34), chr(92) + chr(34))}"'
                    for key, value_ in labels
                )
                lines.append(f"{safe_name}{{{rendered_labels}}} {value}")
            else:
                lines.append(f"{safe_name} {value}")
        return "\n".join(lines) + "\n"

