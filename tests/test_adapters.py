import base64
import json

import httpx
import pytest

from voice_stream_slo.providers.base import ProviderConfig
from voice_stream_slo.providers.cartesia import CartesiaAdapter
from voice_stream_slo.providers.deepgram import DeepgramAdapter
from voice_stream_slo.providers.elevenlabs import ElevenLabsAdapter
from voice_stream_slo.providers.openai import OpenAIAdapter
from voice_stream_slo.schema import AudioSpec


def _config(name: str, endpoint: str, transport: str, **extra: str) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        endpoint=endpoint,
        model="model",
        voice="voice",
        transport=transport,
        key_env="TEST_API_KEY",
        timeout_seconds=5,
        extra=extra,
    )


class _ByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


@pytest.mark.asyncio
async def test_openai_http_chunks_become_pcm_events() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/v1/audio/speech"
        assert payload["response_format"] == "pcm"
        return httpx.Response(200, stream=_ByteStream([bytes(960), bytes(1_920)]))

    adapter = OpenAIAdapter(
        _config("openai", "https://example.test/v1/audio/speech", "http-chunked"),
        "secret",
        AudioSpec(),
    )
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    trace = await adapter.synthesize("trace", "prompt", "Hello.")
    await adapter.close()

    assert [chunk.size_bytes for chunk in trace.chunks] == [960, 1_920]
    assert trace.total_audio_ms == pytest.approx(60.0)


@pytest.mark.asyncio
async def test_elevenlabs_requests_common_pcm_format() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path.endswith("/voice/stream")
        assert request.url.params["output_format"] == "pcm_24000"
        assert payload["model_id"] == "model"
        return httpx.Response(200, stream=_ByteStream([bytes(1_920)]))

    adapter = ElevenLabsAdapter(
        _config("elevenlabs", "https://example.test/v1/text-to-speech", "http-chunked"),
        "secret",
        AudioSpec(),
    )
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    trace = await adapter.synthesize("trace", "prompt", "Hello.")
    await adapter.close()
    assert trace.total_audio_ms == pytest.approx(40.0)


class _FakeSocket:
    def __init__(self, messages: list[str | bytes]) -> None:
        self.messages = list(messages)
        self.sent: list[dict[str, object]] = []
        self.close_code = None

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def recv(self) -> str | bytes:
        return self.messages.pop(0)

    async def close(self) -> None:
        self.close_code = 1000


@pytest.mark.asyncio
async def test_cartesia_decodes_base64_audio_frames() -> None:
    audio_payload = bytes(1_920)
    socket = _FakeSocket(
        [
            json.dumps(
                {
                    "type": "chunk",
                    "context_id": "trace",
                    "data": base64.b64encode(audio_payload).decode(),
                    "step_time": 12,
                }
            ),
            json.dumps({"type": "done", "context_id": "trace", "done": True}),
        ]
    )
    adapter = CartesiaAdapter(
        _config(
            "cartesia",
            "wss://example.test/tts/websocket",
            "websocket",
            api_version="2026-03-01",
        ),
        "secret",
        AudioSpec(),
    )
    adapter._socket = socket
    trace = await adapter.synthesize("trace", "prompt", "Hello.")

    assert socket.sent[0]["output_format"] == {
        "container": "raw",
        "encoding": "pcm_s16le",
        "sample_rate": 24_000,
    }
    assert trace.total_audio_ms == pytest.approx(40.0)


@pytest.mark.asyncio
async def test_deepgram_stops_after_speech_metadata() -> None:
    socket = _FakeSocket(
        [
            json.dumps({"type": "SpeechStarted", "speech_id": "private-id"}),
            bytes(1_920),
            json.dumps(
                {
                    "type": "SpeechMetadata",
                    "speech_id": "private-id",
                    "audio_duration_ms": 40,
                }
            ),
        ]
    )
    adapter = DeepgramAdapter(
        _config("deepgram", "wss://example.test/v2/speak", "websocket"),
        "secret",
        AudioSpec(),
    )
    adapter._socket = socket
    trace = await adapter.synthesize("trace", "prompt", "Hello.")

    assert socket.sent == [
        {"type": "Speak", "text": "Hello."},
        {"type": "Flush"},
    ]
    assert trace.total_audio_ms == pytest.approx(40.0)
    assert "speech_id" not in trace.metadata["speech_metadata"]
