"""Metric definitions derived only from client receive timestamps and PCM bytes."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from voice_stream_slo.buffer import simulate_jitter_buffer
from voice_stream_slo.schema import Trace


def _percentile(values: list[float], percentile: float) -> float:
    return float(np.percentile(values, percentile)) if values else 0.0


def chunk_rows(trace: Trace) -> list[dict[str, float | int | str]]:
    """Return one row per audio receive event with pacing diagnostics."""

    rows: list[dict[str, float | int | str]] = []
    cumulative_audio_ms = 0.0
    previous_arrival_ms: float | None = None
    previous_media_ms: float | None = None

    for chunk in trace.chunks:
        cumulative_audio_ms += chunk.media_duration_ms
        interarrival_ms = (
            0.0 if previous_arrival_ms is None else chunk.arrival_ms - previous_arrival_ms
        )
        pacing_error_ms = (
            0.0 if previous_media_ms is None else interarrival_ms - previous_media_ms
        )
        rows.append(
            {
                "trace_id": trace.trace_id,
                "provider": trace.provider,
                "model": trace.model,
                "prompt_id": trace.prompt_id,
                "sequence": chunk.sequence,
                "arrival_ms": chunk.arrival_ms,
                "size_bytes": chunk.size_bytes,
                "media_duration_ms": chunk.media_duration_ms,
                "interarrival_ms": interarrival_ms,
                "pacing_error_ms": pacing_error_ms,
                "cumulative_audio_ms": cumulative_audio_ms,
                "utterance_progress": cumulative_audio_ms / trace.total_audio_ms,
                "cumulative_delivery_rtf": chunk.arrival_ms / cumulative_audio_ms,
            }
        )
        previous_arrival_ms = chunk.arrival_ms
        previous_media_ms = chunk.media_duration_ms
    return rows


def trace_metric_rows(
    trace: Trace,
    buffer_depths_ms: Iterable[float],
) -> list[dict[str, float | int | str | bool]]:
    """Return one summary row per trace and jitter-buffer depth."""

    trace.validate()
    arrivals = [chunk.arrival_ms for chunk in trace.chunks]
    interarrivals = [
        later - earlier
        for earlier, later in zip(arrivals[:-1], arrivals[1:], strict=True)
    ]
    pacing_errors = [
        gap - previous.media_duration_ms
        for gap, previous in zip(interarrivals, trace.chunks[:-1], strict=True)
    ]
    cumulative_rows = chunk_rows(trace)
    prefix_rtfs = [float(row["cumulative_delivery_rtf"]) for row in cumulative_rows]

    base: dict[str, float | int | str | bool] = {
        "trace_id": trace.trace_id,
        "provider": trace.provider,
        "model": trace.model,
        "voice": trace.voice,
        "prompt_id": trace.prompt_id,
        "text_chars": trace.text_chars,
        "transport": trace.transport,
        "connection_reused": trace.connection_reused,
        "connection_setup_ms": trace.connection_setup_ms,
        "ttfa_ms": arrivals[0],
        "last_audio_arrival_ms": arrivals[-1],
        "completion_ms": trace.completed_ms,
        "audio_ms": trace.total_audio_ms,
        "chunk_count": len(trace.chunks),
        "delivery_rtf": arrivals[-1] / trace.total_audio_ms,
        "completion_rtf": trace.completed_ms / trace.total_audio_ms,
        "interarrival_p50_ms": _percentile(interarrivals, 50),
        "interarrival_p95_ms": _percentile(interarrivals, 95),
        "interarrival_p99_ms": _percentile(interarrivals, 99),
        "interarrival_max_ms": max(interarrivals, default=0.0),
        "pacing_error_p50_ms": _percentile(pacing_errors, 50),
        "pacing_error_p95_ms": _percentile(pacing_errors, 95),
        "pacing_error_p99_ms": _percentile(pacing_errors, 99),
        "pacing_error_max_ms": max(pacing_errors, default=0.0),
        "positive_pacing_error_rate": (
            sum(value > 0 for value in pacing_errors) / len(pacing_errors)
            if pacing_errors
            else 0.0
        ),
        "prefix_rtf_p95": _percentile(prefix_rtfs, 95),
        "prefix_rtf_max": max(prefix_rtfs, default=0.0),
    }

    rows: list[dict[str, float | int | str | bool]] = []
    for depth_ms in buffer_depths_ms:
        simulation = simulate_jitter_buffer(trace.chunks, float(depth_ms))
        recovery_ms = [stall.duration_ms for stall in simulation.stalls]
        rows.append(
            {
                **base,
                "buffer_depth_ms": float(depth_ms),
                "playback_start_ms": simulation.playback_start_ms,
                "post_ttfa_startup_ms": simulation.playback_start_ms - arrivals[0],
                "startup_buffer_ms": simulation.startup_buffer_ms,
                "underrun_count": simulation.underrun_count,
                "glitch_free": simulation.glitch_free,
                "total_stall_ms": simulation.total_stall_ms,
                "max_stall_ms": simulation.max_stall_ms,
                "recovery_p50_ms": _percentile(recovery_ms, 50),
                "recovery_p95_ms": _percentile(recovery_ms, 95),
                "playout_finish_ms": simulation.playout_finish_ms,
            }
        )
    return rows


def stall_rows(
    trace: Trace,
    buffer_depths_ms: Iterable[float],
) -> list[dict[str, float | int | str]]:
    rows: list[dict[str, float | int | str]] = []
    for depth_ms in buffer_depths_ms:
        simulation = simulate_jitter_buffer(trace.chunks, float(depth_ms))
        for index, stall in enumerate(simulation.stalls):
            rows.append(
                {
                    "trace_id": trace.trace_id,
                    "provider": trace.provider,
                    "model": trace.model,
                    "prompt_id": trace.prompt_id,
                    "buffer_depth_ms": float(depth_ms),
                    "stall_index": index,
                    "stall_started_ms": stall.started_ms,
                    "stall_recovered_ms": stall.recovered_ms,
                    "recovery_ms": stall.duration_ms,
                }
            )
    return rows
