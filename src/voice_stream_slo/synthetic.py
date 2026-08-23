"""Deterministic trace fixtures that validate the SLO metrics without API keys."""

from __future__ import annotations

from datetime import UTC, datetime
from math import ceil
from pathlib import Path

import numpy as np

from voice_stream_slo.schema import AudioSpec, ChunkEvent, Trace
from voice_stream_slo.trace_io import write_trace

SCENARIOS = ("steady", "bursty_same_ttfa", "late_but_steady")


def _arrivals(scenario: str, count: int, rng: np.random.Generator) -> list[float]:
    if scenario == "steady":
        ttfa = 125.0 + float(rng.normal(0, 5))
        gaps = [max(18.0, 33.0 + float(rng.normal(0, 3))) for _ in range(count - 1)]
    elif scenario == "bursty_same_ttfa":
        ttfa = 125.0 + float(rng.normal(0, 5))
        pattern = (18.0, 155.0, 18.0, 18.0, 18.0, 18.0)
        gaps = [
            max(5.0, pattern[index % len(pattern)] + float(rng.normal(0, 4)))
            for index in range(count - 1)
        ]
    elif scenario == "late_but_steady":
        ttfa = 220.0 + float(rng.normal(0, 5))
        gaps = [max(18.0, 32.0 + float(rng.normal(0, 2))) for _ in range(count - 1)]
    else:
        raise ValueError(f"unknown synthetic scenario: {scenario}")
    values = [ttfa]
    for gap in gaps:
        values.append(values[-1] + gap)
    return values


def write_synthetic_traces(
    prompts: list[dict[str, str]],
    destination: str | Path,
    audio: AudioSpec,
    repetitions: int,
    seed: int,
) -> list[Path]:
    """Create traces with controlled pacing pathologies and no provider claims."""

    output = Path(destination)
    rng = np.random.default_rng(seed)
    paths: list[Path] = []
    bytes_per_chunk = round(audio.bytes_per_second * 0.04)
    media_ms = audio.duration_ms(bytes_per_chunk)

    for scenario in SCENARIOS:
        for prompt in prompts:
            chunk_count = max(14, ceil(len(prompt["text"]) / 7))
            for repetition in range(repetitions):
                arrivals = _arrivals(scenario, chunk_count, rng)
                chunks = [
                    ChunkEvent(
                        sequence=index,
                        arrival_ms=arrival_ms,
                        size_bytes=bytes_per_chunk,
                        media_duration_ms=media_ms,
                    )
                    for index, arrival_ms in enumerate(arrivals)
                ]
                trace_id = f"{scenario}-{prompt['id']}-r{repetition:03d}"
                trace = Trace.create(
                    trace_id=trace_id,
                    provider=scenario,
                    model="synthetic-validation-v1",
                    voice="deterministic-pcm",
                    prompt_id=prompt["id"],
                    text=prompt["text"],
                    started_at_utc=datetime.now(UTC).isoformat(),
                    transport="synthetic",
                    connection_reused=True,
                    connection_setup_ms=0.0,
                    audio=audio,
                    chunks=chunks,
                    completed_ms=arrivals[-1] + 2.0,
                    metadata={"scenario": scenario, "seed": seed},
                )
                paths.append(write_trace(trace, output / scenario / f"{trace_id}.json"))
    return paths
