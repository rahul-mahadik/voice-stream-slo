"""Common adapter interface and trace construction helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from voice_stream_slo.schema import AudioSpec, ChunkEvent, Trace, chunk_event


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    endpoint: str
    model: str
    voice: str
    transport: str
    key_env: str
    timeout_seconds: float
    extra: dict[str, Any] = field(default_factory=dict)


class ProviderAdapter(ABC):
    """A warmed transport capable of timing one complete TTS turn."""

    def __init__(self, config: ProviderConfig, api_key: str, audio: AudioSpec) -> None:
        self.config = config
        self._api_key = api_key
        self.audio = audio
        self.connection_setup_ms = 0.0

    @abstractmethod
    async def setup(self) -> None:
        """Establish reusable transport state outside the measured turn."""

    @abstractmethod
    async def close(self) -> None:
        """Release transport state."""

    @abstractmethod
    async def synthesize(self, trace_id: str, prompt_id: str, text: str) -> Trace:
        """Generate one turn and return only timing and byte-count telemetry."""

    def _event(self, sequence: int, started: float, payload: bytes) -> ChunkEvent:
        return chunk_event(sequence, (perf_counter() - started) * 1000.0, payload, self.audio)

    def _trace(
        self,
        *,
        trace_id: str,
        prompt_id: str,
        text: str,
        started_at_utc: str,
        chunks: list[ChunkEvent],
        completed_ms: float,
        metadata: dict[str, Any] | None = None,
    ) -> Trace:
        return Trace.create(
            trace_id=trace_id,
            provider=self.config.name,
            model=self.config.model,
            voice=self.config.voice,
            prompt_id=prompt_id,
            text=text,
            started_at_utc=started_at_utc,
            transport=self.config.transport,
            connection_reused=True,
            connection_setup_ms=self.connection_setup_ms,
            audio=self.audio,
            chunks=chunks,
            completed_ms=completed_ms,
            metadata=metadata,
        )

    @staticmethod
    def utc_now() -> str:
        return datetime.now(UTC).isoformat()
