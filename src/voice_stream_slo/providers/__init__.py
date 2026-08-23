"""Provider adapters with a shared client-observed trace contract."""

from voice_stream_slo.providers.base import ProviderAdapter, ProviderConfig
from voice_stream_slo.providers.cartesia import CartesiaAdapter
from voice_stream_slo.providers.deepgram import DeepgramAdapter
from voice_stream_slo.providers.elevenlabs import ElevenLabsAdapter
from voice_stream_slo.providers.openai import OpenAIAdapter

ADAPTERS: dict[str, type[ProviderAdapter]] = {
    "cartesia": CartesiaAdapter,
    "deepgram": DeepgramAdapter,
    "elevenlabs": ElevenLabsAdapter,
    "openai": OpenAIAdapter,
}

__all__ = ["ADAPTERS", "ProviderAdapter", "ProviderConfig"]
