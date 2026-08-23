"""ElevenLabs chunked-HTTP PCM adapter."""

from __future__ import annotations

from time import perf_counter

import httpx

from voice_stream_slo.providers.base import ProviderAdapter
from voice_stream_slo.schema import ChunkEvent, Trace


class ElevenLabsAdapter(ProviderAdapter):
    async def setup(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout_seconds),
            headers={"xi-api-key": self._api_key},
            http2=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def synthesize(self, trace_id: str, prompt_id: str, text: str) -> Trace:
        chunks: list[ChunkEvent] = []
        started_at_utc = self.utc_now()
        started = perf_counter()
        url = f"{self.config.endpoint}/{self.config.voice}/stream"
        params = {"output_format": f"pcm_{self.audio.sample_rate_hz}"}
        payload = {"text": text, "model_id": self.config.model}
        async with self._client.stream("POST", url, params=params, json=payload) as response:
            response.raise_for_status()
            async for data in response.aiter_raw():
                if data:
                    chunks.append(self._event(len(chunks), started, data))
        completed_ms = (perf_counter() - started) * 1000.0
        return self._trace(
            trace_id=trace_id,
            prompt_id=prompt_id,
            text=text,
            started_at_utc=started_at_utc,
            chunks=chunks,
            completed_ms=completed_ms,
            metadata={
                "output_format": f"pcm_{self.audio.sample_rate_hz}",
                "http_version": response.http_version,
            },
        )
