"""Portable trace schema for client-observed streaming audio events."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any


@dataclass(frozen=True)
class AudioSpec:
    """Raw PCM layout used by every adapter in the benchmark."""

    sample_rate_hz: int = 24_000
    sample_width_bytes: int = 2
    channels: int = 1

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate_hz * self.sample_width_bytes * self.channels

    def duration_ms(self, size_bytes: int) -> float:
        if size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        return 1000.0 * size_bytes / self.bytes_per_second


@dataclass(frozen=True)
class ChunkEvent:
    """One client receive event containing playable PCM bytes."""

    sequence: int
    arrival_ms: float
    size_bytes: int
    media_duration_ms: float


@dataclass
class Trace:
    """One complete TTS turn, timed from application payload send."""

    trace_id: str
    provider: str
    model: str
    voice: str
    prompt_id: str
    text_sha256: str
    text_chars: int
    started_at_utc: str
    transport: str
    connection_reused: bool
    connection_setup_ms: float
    audio: AudioSpec
    chunks: list[ChunkEvent]
    completed_ms: float
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"

    @classmethod
    def create(
        cls,
        *,
        trace_id: str,
        provider: str,
        model: str,
        voice: str,
        prompt_id: str,
        text: str,
        started_at_utc: str,
        transport: str,
        connection_reused: bool,
        connection_setup_ms: float,
        audio: AudioSpec,
        chunks: list[ChunkEvent],
        completed_ms: float,
        success: bool = True,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Trace:
        return cls(
            trace_id=trace_id,
            provider=provider,
            model=model,
            voice=voice,
            prompt_id=prompt_id,
            text_sha256=sha256(text.encode("utf-8")).hexdigest(),
            text_chars=len(text),
            started_at_utc=started_at_utc,
            transport=transport,
            connection_reused=connection_reused,
            connection_setup_ms=connection_setup_ms,
            audio=audio,
            chunks=chunks,
            completed_ms=completed_ms,
            success=success,
            error=error,
            metadata=metadata or {},
        )

    @property
    def total_audio_ms(self) -> float:
        return sum(chunk.media_duration_ms for chunk in self.chunks)

    @property
    def total_bytes(self) -> int:
        return sum(chunk.size_bytes for chunk in self.chunks)

    def validate(self) -> None:
        if self.completed_ms < 0:
            raise ValueError("completed_ms must be non-negative")
        previous = -1.0
        for expected_sequence, chunk in enumerate(self.chunks):
            if chunk.sequence != expected_sequence:
                raise ValueError("chunk sequences must be contiguous and zero-based")
            if chunk.arrival_ms < previous:
                raise ValueError("chunk arrivals must be monotonic")
            if chunk.size_bytes <= 0 or chunk.media_duration_ms <= 0:
                raise ValueError("audio chunks must be non-empty")
            expected_ms = self.audio.duration_ms(chunk.size_bytes)
            if abs(expected_ms - chunk.media_duration_ms) > 0.02:
                raise ValueError("media duration does not match the PCM byte count")
            previous = chunk.arrival_ms
        if self.chunks and self.completed_ms < self.chunks[-1].arrival_ms:
            raise ValueError("completion cannot precede the final audio chunk")
        if self.success and not self.chunks:
            raise ValueError("a successful trace must contain audio")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Trace:
        data = dict(payload)
        data["audio"] = AudioSpec(**data["audio"])
        data["chunks"] = [ChunkEvent(**chunk) for chunk in data["chunks"]]
        trace = cls(**data)
        trace.validate()
        return trace


def chunk_event(sequence: int, arrival_ms: float, data: bytes, audio: AudioSpec) -> ChunkEvent:
    """Build a trace event without retaining provider audio payloads."""

    return ChunkEvent(
        sequence=sequence,
        arrival_ms=arrival_ms,
        size_bytes=len(data),
        media_duration_ms=audio.duration_ms(len(data)),
    )
