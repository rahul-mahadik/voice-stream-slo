"""Cartesia context-based WebSocket PCM adapter."""

from __future__ import annotations

import asyncio
import base64
import json
from time import perf_counter

from websockets.asyncio.client import connect

from voice_stream_slo.providers.base import ProviderAdapter
from voice_stream_slo.schema import ChunkEvent, Trace


class CartesiaAdapter(ProviderAdapter):
    async def setup(self) -> None:
        started = perf_counter()
        self._socket = await connect(
            self.config.endpoint,
            additional_headers={
                "X-API-Key": self._api_key,
                "Cartesia-Version": str(self.config.extra["api_version"]),
            },
            max_size=None,
            ping_interval=20,
        )
        self.connection_setup_ms = (perf_counter() - started) * 1000.0

    async def close(self) -> None:
        await self._socket.close()

    async def synthesize(self, trace_id: str, prompt_id: str, text: str) -> Trace:
        chunks: list[ChunkEvent] = []
        server_step_ms: list[float] = []
        started_at_utc = self.utc_now()
        request = {
            "model_id": self.config.model,
            "transcript": text,
            "voice": {"mode": "id", "id": self.config.voice},
            "language": "en",
            "context_id": trace_id,
            "output_format": {
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": self.audio.sample_rate_hz,
            },
            "add_timestamps": False,
            "continue": False,
        }
        started = perf_counter()
        await self._socket.send(json.dumps(request))
        async with asyncio.timeout(self.config.timeout_seconds):
            while True:
                message = await self._socket.recv()
                if isinstance(message, bytes):
                    raise RuntimeError("unexpected binary Cartesia WebSocket frame")
                event = json.loads(message)
                if event.get("context_id") not in {None, trace_id}:
                    continue
                event_type = event.get("type")
                if event_type == "chunk":
                    payload = base64.b64decode(event["data"])
                    if payload:
                        chunks.append(self._event(len(chunks), started, payload))
                    if event.get("step_time") is not None:
                        server_step_ms.append(float(event["step_time"]))
                elif event_type == "error":
                    raise RuntimeError(f"Cartesia TTS error: {event}")
                elif event.get("done") or event_type == "done":
                    break
        completed_ms = (perf_counter() - started) * 1000.0
        return self._trace(
            trace_id=trace_id,
            prompt_id=prompt_id,
            text=text,
            started_at_utc=started_at_utc,
            chunks=chunks,
            completed_ms=completed_ms,
            metadata={
                "server_step_ms": server_step_ms,
                "api_version": self.config.extra["api_version"],
            },
        )
