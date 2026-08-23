"""Stable JSON storage for raw benchmark traces."""

from __future__ import annotations

import json
from pathlib import Path

from voice_stream_slo.schema import Trace


def write_trace(trace: Trace, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(trace.to_dict(), indent=2, sort_keys=True) + "\n")
    return destination


def read_trace(path: str | Path) -> Trace:
    return Trace.from_dict(json.loads(Path(path).read_text()))


def read_traces(root: str | Path) -> list[Trace]:
    return [read_trace(path) for path in sorted(Path(root).rglob("*.json"))]
