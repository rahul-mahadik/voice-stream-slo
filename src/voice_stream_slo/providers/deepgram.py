"""Deepgram Flux turn-based WebSocket PCM adapter."""

from __future__ import annotations

import asyncio
import json
from time import perf_counter
from urllib.parse import urlencode

from websockets.asyncio.client import connect

from voice_stream_slo.providers.base import ProviderAdapter
from voice_stream_slo.schema import ChunkEvent, Trace


class DeepgramAdapter(ProviderAdapter):
    async def setup(self) -> None:
        query = urlencode(
            {
                "model": self.config.model,
                "encoding": "linear16",
                "sample_rate": self.audio.sample_rate_hz,
            }
        )
        started = perf_counter()
        self._socket = await connect(
            f"{self.config.endpoint}?{query}",
            additional_headers={"Authorization": f"Token {self._api_key}"},
            max_size=None,
            ping_interval=20,
        )
        self.connection_setup_ms = (perf_counter() - started) * 1000.0

    async def close(self) -> None:
        if not self._socket.close_code:
            await self._socket.send(json.dumps({"type": "Close"}))
        await self._socket.close()

    async def synthesize(self, trace_id: str, prompt_id: str, text: str) -> Trace:
        chunks: list[ChunkEvent] = []
        lifecycle: list[dict[str, object]] = []
        started_at_utc = self.utc_now()
        started = perf_counter()
        await self._socket.send(json.dumps({"type": "Speak", "text": text}))
        await self._socket.send(json.dumps({"type": "Flush"}))
        async with asyncio.timeout(self.config.timeout_seconds):
            while True:
                message = await self._socket.recv()
                if isinstance(message, bytes):
                    if message:
                        chunks.append(self._event(len(chunks), started, message))
                    continue
                event = json.loads(message)
                event_type = event.get("type")
                lifecycle.append(
                    {
                        "type": event_type,
                        "arrival_ms": (perf_counter() - started) * 1000.0,
                    }
                )
                if event_type in {"Error", "FatalError"}:
                    raise RuntimeError(f"Deepgram TTS error: {event}")
                if event_type == "SpeechMetadata":
                    metadata = {
                        key: value
                        for key, value in event.items()
                        if key not in {"request_id", "speech_id"}
                    }
                    break
        completed_ms = (perf_counter() - started) * 1000.0
        return self._trace(
            trace_id=trace_id,
            prompt_id=prompt_id,
            text=text,
            started_at_utc=started_at_utc,
            chunks=chunks,
            completed_ms=completed_ms,
            metadata={"lifecycle": lifecycle, "speech_metadata": metadata},
        )
