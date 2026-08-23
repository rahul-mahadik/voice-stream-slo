# Provider notes and primary sources

The adapters target each provider's documented low-latency agent path while normalizing output to 24 kHz signed PCM. These notes are implementation provenance, not endorsements.

## Cartesia

- Model: immutable `sonic-3.5-2026-05-04` snapshot.
- Transport: context-based TTS WebSocket with API version `2026-03-01`.
- Output: raw `pcm_s16le`, 24 kHz.
- Timer starts before sending a full generation request on an established socket and ends on the `done` event.

Sources: [Sonic 3.5 model and snapshot policy](https://docs.cartesia.ai/build-with-cartesia/tts-models/latest), [TTS WebSocket protocol](https://docs.cartesia.ai/api-reference/tts/websocket), and [2025 changelog](https://docs.cartesia.ai/changelog/2025).

## Deepgram

- Model/voice: `flux-haley-en`.
- Transport: Flux `/v2/speak` persistent WebSocket.
- Output: raw `linear16`, 24 kHz.
- Timer starts before a full `Speak` message followed by `Flush`; `SpeechMetadata` marks completion.

Flux maintains conversational state across turns. The benchmark keeps one warmed connection, matching its documented agent-oriented lifecycle; this semantic difference is declared rather than hidden.

Sources: [Flux TTS quickstart and transport](https://developers.deepgram.com/docs/flux-tts/quickstart), [client messages](https://developers.deepgram.com/docs/flux-tts/client-messages), and [speech lifecycle](https://developers.deepgram.com/docs/flux-tts/state).

## ElevenLabs

- Model: `eleven_flash_v2_5`.
- Transport: streaming HTTP endpoint for complete text.
- Output: `pcm_24000`.
- Timer starts immediately before the POST and ends when the response body stream closes.

ElevenLabs describes Flash's latency figure as inference-only and notes that end-to-end latency varies with location and endpoint. That distinction is exactly why this benchmark records the client receive path.

Sources: [stream speech API](https://elevenlabs.io/docs/api-reference/text-to-speech/stream), [model selection](https://elevenlabs.io/docs/overview/models), and [latency guidance](https://elevenlabs.io/docs/developer-guides/reducing-latency).

## OpenAI

- Model: `gpt-4o-mini-tts` with the `marin` voice.
- Transport: Speech API over chunked HTTP.
- Output: raw PCM, documented as 24 kHz signed 16-bit little-endian.
- Timer starts immediately before the POST and ends when the response body stream closes.

Source: [official OpenAI text-to-speech guide](https://developers.openai.com/api/docs/guides/text-to-speech).

## Claim taxonomy

Published latency figures are not automatically contradictory when they time different boundaries. Model inference, first server byte, first client PCM, application callback, and first speaker output are distinct measurements. For example, Cartesia's release material distinguishes model latency from end-to-end conversational latency, while ElevenLabs explicitly labels its Flash figure as model inference excluding network and application latency. The benchmark does not adjudicate marketing language; it names its boundary and publishes raw client-observed distributions.
