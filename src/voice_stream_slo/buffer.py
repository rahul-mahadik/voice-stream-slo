"""Deterministic client-side playback and jitter-buffer simulation."""

from __future__ import annotations

from dataclasses import dataclass

from voice_stream_slo.schema import ChunkEvent


@dataclass(frozen=True)
class Stall:
    started_ms: float
    recovered_ms: float

    @property
    def duration_ms(self) -> float:
        return self.recovered_ms - self.started_ms


@dataclass(frozen=True)
class BufferSimulation:
    depth_ms: float
    playback_start_ms: float
    startup_buffer_ms: float
    underrun_count: int
    total_stall_ms: float
    max_stall_ms: float
    playout_finish_ms: float
    stalls: tuple[Stall, ...]

    @property
    def glitch_free(self) -> bool:
        return self.underrun_count == 0


def simulate_jitter_buffer(
    chunks: list[ChunkEvent],
    depth_ms: float,
) -> BufferSimulation:
    """Replay receive events through a prebuffer-and-immediate-recovery player.

    Playback begins on the first receive event at which at least ``depth_ms``
    of PCM has accumulated. After a starvation event, playback resumes as soon
    as the next non-empty audio event arrives. Waiting after the last audio
    frame is not counted as a stall: the utterance has ended normally.
    """

    if depth_ms < 0:
        raise ValueError("depth_ms must be non-negative")
    if not chunks:
        raise ValueError("at least one chunk is required")

    ordered = sorted(chunks, key=lambda chunk: (chunk.arrival_ms, chunk.sequence))
    buffered_ms = 0.0
    start_index = len(ordered) - 1
    playback_start_ms = ordered[-1].arrival_ms

    for index, chunk in enumerate(ordered):
        buffered_ms += chunk.media_duration_ms
        if depth_ms == 0 or buffered_ms + 1e-9 >= depth_ms:
            start_index = index
            playback_start_ms = chunk.arrival_ms
            break

    startup_buffer_ms = buffered_ms
    last_event_ms = playback_start_ms
    playing = True
    stalls: list[Stall] = []

    for chunk in ordered[start_index + 1 :]:
        elapsed_ms = chunk.arrival_ms - last_event_ms
        if playing and elapsed_ms > buffered_ms + 1e-9:
            starvation_ms = last_event_ms + buffered_ms
            stalls.append(Stall(started_ms=starvation_ms, recovered_ms=chunk.arrival_ms))
            buffered_ms = 0.0
            playing = False
        elif playing:
            buffered_ms = max(0.0, buffered_ms - elapsed_ms)

        buffered_ms += chunk.media_duration_ms
        if not playing:
            playing = True
        last_event_ms = chunk.arrival_ms

    playout_finish_ms = last_event_ms + buffered_ms
    total_stall_ms = sum(stall.duration_ms for stall in stalls)
    max_stall_ms = max((stall.duration_ms for stall in stalls), default=0.0)
    return BufferSimulation(
        depth_ms=depth_ms,
        playback_start_ms=playback_start_ms,
        startup_buffer_ms=startup_buffer_ms,
        underrun_count=len(stalls),
        total_stall_ms=total_stall_ms,
        max_stall_ms=max_stall_ms,
        playout_finish_ms=playout_finish_ms,
        stalls=tuple(stalls),
    )
