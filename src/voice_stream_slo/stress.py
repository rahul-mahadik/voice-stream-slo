"""Controlled downstream receive-pause replay for captured PCM traces."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from voice_stream_slo.buffer import simulate_jitter_buffer
from voice_stream_slo.schema import ChunkEvent, Trace


def inject_receive_pause(
    chunks: list[ChunkEvent],
    pause_ms: float,
    audio_fraction: float,
) -> list[ChunkEvent]:
    """Delay a suffix of receive events by a fixed amount.

    The suffix begins at the first event whose cumulative PCM crosses the
    requested fraction of the utterance. Shifting the entire suffix preserves
    ordering and models a one-off last-mile delivery pause without claiming
    that the provider itself produced the pause.
    """

    if not chunks:
        raise ValueError("at least one chunk is required")
    if pause_ms < 0:
        raise ValueError("pause_ms must be non-negative")
    if not 0.0 < audio_fraction < 1.0:
        raise ValueError("audio_fraction must be between zero and one")

    total_audio_ms = sum(chunk.media_duration_ms for chunk in chunks)
    threshold_ms = total_audio_ms * audio_fraction
    cumulative_ms = 0.0
    split_index = len(chunks) - 1
    for index, chunk in enumerate(chunks):
        cumulative_ms += chunk.media_duration_ms
        if cumulative_ms + 1e-9 >= threshold_ms:
            split_index = index
            break

    return [
        replace(
            chunk,
            arrival_ms=chunk.arrival_ms + (pause_ms if index >= split_index else 0.0),
        )
        for index, chunk in enumerate(chunks)
    ]


def stress_replay_rows(
    trace: Trace,
    buffer_depth_ms: float,
    pause_durations_ms: Iterable[float],
    injection_audio_fractions: Iterable[float],
) -> list[dict[str, float | int | str | bool]]:
    """Return one controlled replay outcome per pause and injection point."""

    rows: list[dict[str, float | int | str | bool]] = []
    for pause_ms in pause_durations_ms:
        for audio_fraction in injection_audio_fractions:
            shifted = inject_receive_pause(trace.chunks, float(pause_ms), float(audio_fraction))
            simulation = simulate_jitter_buffer(shifted, float(buffer_depth_ms))
            rows.append(
                {
                    "trace_id": trace.trace_id,
                    "provider": trace.provider,
                    "model": trace.model,
                    "prompt_id": trace.prompt_id,
                    "buffer_depth_ms": float(buffer_depth_ms),
                    "pause_ms": float(pause_ms),
                    "injection_audio_fraction": float(audio_fraction),
                    "glitch_free": simulation.glitch_free,
                    "underrun_count": simulation.underrun_count,
                    "total_stall_ms": simulation.total_stall_ms,
                    "max_stall_ms": simulation.max_stall_ms,
                }
            )
    return rows
