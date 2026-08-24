# Voice Stream SLO Lab

- **Question**
  - Time to first audio measures how quickly speech starts.
  - This benchmark measures whether audio keeps arriving fast enough to avoid silence after playback starts.

- **Live run**
  - Providers
    - Cartesia Sonic 3.5
    - Deepgram Flux
    - ElevenLabs Flash
  - Workload
    - 6 English agent prompts
    - 20 repetitions per prompt and provider
    - 360 requests total
    - Warmed, interleaved, and issued one at a time
  - Audio format
    - Raw signed 16-bit PCM
    - 24 kHz
    - Mono

- **Results**
  - Baseline playback
    - Cartesia: 120 of 120 traces remained playable
    - Deepgram: 120 of 120 traces remained playable
    - ElevenLabs: 120 of 120 traces remained playable
    - No trace underran at the tested starting buffers from 0 to 200 ms
  - Median time to first audio
    - Cartesia: 91.4 ms
    - Deepgram: 93.2 ms
    - ElevenLabs: 195.2 ms
  - Median delivery real-time factor
    - Cartesia: 0.118
    - Deepgram: 0.614
    - ElevenLabs: 0.059
    - Lower values mean audio was delivered faster relative to its playback duration
  - Survival after an artificial 400 ms receive pause
    - Cartesia: 90.8%
    - Deepgram: 66.7%
    - ElevenLabs: 100%

- **Interpretation**
  - All three providers completed the baseline run without a mid-utterance underrun.
  - Cartesia and Deepgram began playback sooner than ElevenLabs.
  - ElevenLabs began later but delivered more audio ahead of the playhead.
  - The pause result measures delivery headroom in the recorded traces.
    - The pause was added during replay.
    - It was not a provider outage observed during collection.
    - Sending more audio ahead naturally improves pause survival.

- **Figures**
  - Controlled receive-pause replay
    - ![Controlled receive-pause replay](results/live/2026-08-23-three-provider/analysis/figures/stress_pause_curve.png)
  - Delivery speed over the utterance
    - ![Delivery RTF over the utterance](results/live/2026-08-23-three-provider/analysis/figures/rtf_over_utterance.png)

- **Measured from each trace**
  - Time to first playable audio
  - Inter-chunk arrival gaps and jitter
  - Delivery speed relative to audio duration
  - Mid-utterance underruns at several starting-buffer depths
  - Recovery time after an underrun
  - Playable success rate, including failed requests in the denominator
  - Recorded data
    - Arrival time of each playable receive event
    - Byte count of each event
    - No retained raw audio

- **Run the offline demo**
  - No API keys or network access are required

    ```bash
    python -m pip install -e '.[dev]'
    voice-stream-slo demo --output results/synthetic
    python -m pytest
    ```

- **Run a live benchmark**
  - Copy `.env.example` to the gitignored `.env`
  - Add provider API keys
  - Set `network_label` in `configs/benchmark.json`
  - Collect and analyze traces

    ```bash
    voice-stream-slo run \
      --config configs/benchmark.json \
      --output results/live/my-run

    voice-stream-slo analyze \
      --config configs/benchmark.json \
      --input results/live/my-run/raw/traces \
      --output results/live/my-run/analysis
    ```

- **Included adapters**
  - Cartesia Sonic 3.5
  - Deepgram Flux
  - ElevenLabs Flash
  - OpenAI `gpt-4o-mini-tts`
    - Not included in the published live run

- **Detailed evidence**
  - [Live report](results/live/2026-08-23-three-provider/analysis/report.md)
    - Confidence intervals
    - Prompt-level results
    - Long-form tables
  - [Methodology](docs/methodology.md)
    - Metric definitions
    - Buffer simulation
    - Statistical intervals
  - [Provider notes](docs/provider_notes.md)
    - API choices
    - Transport differences
    - Timing boundaries

- **Limits**
  - One client location
  - Low request load
  - Six English prompts
  - Application-visible delivery rather than model-only latency
  - Different transport behavior
    - WebSockets expose message frames
    - HTTP clients may combine network reads
  - No voice-quality evaluation
  - Not a global provider ranking

- **License**
  - Code: MIT
  - Provider names and trademarks belong to their owners
