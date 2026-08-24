# Voice Stream SLO Lab

Most streaming TTS benchmarks stop at time to first audio. This project asks what happens next: once playback starts, does audio keep arriving fast enough to avoid silence?

## Result

The first live run sent six English agent prompts to three providers, 20 times each. Requests were warmed, interleaved, and issued one at a time. All 360 responses produced valid 24 kHz PCM.

| Provider | Median TTFA | Baseline playable | Median delivery RTF | Survived a 400 ms pause |
|---|---:|---:|---:|---:|
| Cartesia Sonic 3.5 | 91.4 ms | 100% | 0.118 | 90.8% |
| Deepgram Flux | 93.2 ms | 100% | 0.614 | 66.7% |
| ElevenLabs Flash | 195.2 ms | 100% | 0.059 | 100% |

Under the recorded network conditions, none of the providers underran after playback began. The main difference was how they delivered audio: Cartesia and Deepgram started sooner, while ElevenLabs started later and then delivered audio more quickly relative to playback time.

To make those pacing differences visible, the analysis replays each trace with an artificial receive pause. At 400 ms, survival ranged from 66.7% to 100%.

![Controlled receive-pause replay](results/live/2026-08-23-three-provider/analysis/figures/stress_pause_curve.png)

![Delivery RTF over the utterance](results/live/2026-08-23-three-provider/analysis/figures/rtf_over_utterance.png)

The pause is a controlled stress test, not a provider outage that happened during collection. A provider that sends more audio ahead of the playhead will naturally do better on this test. See the [live report](results/live/2026-08-23-three-provider/analysis/report.md) for confidence intervals and full tables.

## What is measured

The client records when each playable block of audio arrives and how many bytes it contains. Raw audio is not retained. From that event stream, it calculates:

- time to first playable audio
- inter-chunk gaps and delivery jitter
- delivery speed relative to audio duration
- mid-utterance underruns at several starting-buffer depths
- recovery time after an underrun

All providers return raw signed 16-bit, 24 kHz, mono PCM, so the playback simulation uses the same audio clock for every trace. Metric definitions are in the [methodology](docs/methodology.md); request and transport choices are in the [provider notes](docs/provider_notes.md).

## Run it

The offline demo validates the analysis without API keys:

```bash
python -m pip install -e '.[dev]'
voice-stream-slo demo --output results/synthetic
python -m pytest
```

For a live run, copy `.env.example` to `.env`, add provider keys, and set the `network_label` in `configs/benchmark.json`:

```bash
voice-stream-slo run \
  --config configs/benchmark.json \
  --output results/live/my-run

voice-stream-slo analyze \
  --config configs/benchmark.json \
  --input results/live/my-run/raw/traces \
  --output results/live/my-run/analysis
```

Adapters are included for Cartesia Sonic 3.5, Deepgram Flux, ElevenLabs Flash, and OpenAI `gpt-4o-mini-tts`. The published run used the first three.

## Limits

This is a low-load measurement from one client location. It compares application-visible delivery, not voice quality or the models in isolation. WebSockets expose message frames, while HTTP clients may combine network reads. The results should not be read as a global provider ranking.

Code is MIT licensed. Provider names and trademarks belong to their owners.
