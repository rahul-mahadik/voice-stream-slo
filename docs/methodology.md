# Methodology

## Research question

For a completed text input sent to a warmed streaming TTS service, how reliably can a client play the returned utterance without starving its audio buffer?

The unit of analysis is one provider × prompt × repetition trace. The observable boundary is the benchmark process receiving playable PCM—not a server-side timing header, SDK callback scheduled later, audio-device latency, or model-only inference time.

## Controlled protocol

- **Audio:** raw signed 16-bit little-endian PCM, 24,000 Hz, mono.
- **Input:** six fixed, punctuated English agent utterances in short, medium, and long bands.
- **Input availability:** the complete utterance is sent at application request time. Incremental LLM-token timing is out of scope.
- **Load:** one measured request globally in flight at a time. This is a low-load baseline, not a concurrency test.
- **Warm state:** establish reusable transports and run two excluded warmups per provider.
- **Ordering:** deterministically shuffle the full provider × prompt × repetition matrix with the declared run seed.
- **Repetitions:** 20 per prompt and provider by default.
- **Cadence:** wait 250 ms between measured turns by default.
- **Clock:** use the local monotonic high-resolution clock for intervals; record UTC only for run provenance.
- **Storage:** retain receive timestamps, byte counts, declared models, and non-secret server metadata. Do not retain raw audio by default.

Persistent WebSockets and pooled HTTP connections match their intended agent integrations. Connection establishment is outside measured TTFA for both. WebSocket handshake duration is retained as a diagnostic where directly observable; it is not added to the turn metric.

## Metric definitions

Let `t0` be the instant immediately before the request payload is sent. For received audio event `i`:

- `a_i` is its arrival time relative to `t0`.
- `b_i` is its PCM byte count.
- `d_i = 1000 b_i / (sample_rate × sample_width × channels)` is playable audio in milliseconds.

### Time to first audio

`TTFA = a_1`.

Only non-empty, playable PCM establishes first audio. Response headers and JSON lifecycle messages do not.

### Inter-chunk timing and pacing error

For `i > 1`, the raw inter-arrival gap is:

`g_i = a_i - a_(i-1)`.

Raw gaps are affected by provider frame sizing, so the primary normalized diagnostic is:

`p_i = g_i - d_(i-1)`.

Positive pacing error means the gap consumed more time than the preceding event supplied and therefore placed pressure on the client buffer. Negative pacing error means delivery got ahead of playback. The report publishes both distributions instead of collapsing them into one average “jitter” number.

### Delivery real-time factor

At audio prefix `i`:

`RTF_i = a_i / sum(d_1 ... d_i)`.

The full-utterance delivery RTF uses the final audio arrival. Values below one indicate delivery finished faster than real-time overall, but do **not** guarantee glitch-free playback: local gaps can still drain the buffer. The prefix trajectory exposes that distinction.

### Jitter-buffer replay

For declared depth `B`, the simulator:

1. Accumulates received PCM until at least `B` milliseconds are available.
2. Starts playback at that receive event.
3. Consumes buffered media continuously between receive events.
4. Records an underrun if the buffer reaches zero before another audio event arrives.
5. Resumes immediately when the next non-empty audio event arrives.
6. Does not count the natural end of the final audio event as starvation.

This intentionally simple policy makes `B` an initial prebuffer target and makes recovery duration directly observable. Production players with adaptive rebuffer thresholds can replay the raw traces under a different policy.

Published depths are 0, 20, 40, 80, 120, and 200 ms. For each trace and depth, the analysis reports playback start, underrun count, total and maximum stalled time, recovery distribution, and playout completion.

The target depth is rounded up to a whole client receive event. `startup_buffer_ms` therefore
reports the actual playable PCM accumulated when playback starts; it can exceed the configured
target when a provider emits larger chunks.

### Controlled downstream pause replay

An ordinary low-load run can deliver every utterance faster than playback and produce no
observed underruns. Rather than misrepresent a flat baseline as a general resilience guarantee,
the analysis includes a separately labeled counterfactual stress replay.

For each recorded trace, a one-off receive pause of 0, 50, 100, 200, 400, 800, or 1,200 ms is
injected when cumulative PCM first crosses 25%, 50%, and 75% of the utterance. The selected
event and every later event are shifted by the same duration, preserving event order and the
recorded post-pause cadence. The primary stress outcome is strict: at an 80 ms jitter-buffer
target, a trace passes only if it remains glitch-free at all three injection locations.

This replay isolates the delivery headroom already present in the captured stream. It does not
claim that a provider produced the pause, predict provider behavior under congestion, or model
packet loss, retransmission, adaptive bitrate, TCP flow control, or a downstream media stack.

### Reliability outcomes

- **Glitch-free rate:** zero simulated underruns, conditional on successful TTS responses.
- **Request-success rate:** fraction of attempted turns that returned valid audio.
- **Playable-success rate:** the request succeeded *and* replay had zero underruns. This is the primary SLO-style outcome; failed requests remain failures rather than disappearing from the denominator.

## Statistical treatment

Point estimates summarize all declared repetitions. Ninety-five percent intervals for continuous
metrics and count summaries use a two-stage hierarchical bootstrap:

1. Resample prompt IDs with replacement.
2. Within each sampled prompt, resample repeated trials with replacement.

This preserves the fact that repeated network trials of one sentence do not create new independent prompts. Six prompts remain a small prompt sample, so intervals describe this workload rather than a universal provider ordering. ECDFs and 10–90% trajectory bands are descriptive distributions, not confidence intervals.

Binary request, glitch-free, playable-success, and strict pause-survival rates take the envelope
of the hierarchical bootstrap interval and a 95% Wilson score interval over traces. This retains
prompt/trial resampling while avoiding the false zero-width interval produced by an ordinary
bootstrap when every observed request succeeds. Six prompts remain the limiting unit for
workload generalization.

## Fairness choices

- The same PCM layout makes every byte directly convertible to playable time without codec startup or decoder buffering.
- Full text is available at request time for all systems.
- The request matrix is interleaved to reduce confounding from time-of-day drift.
- Provider defaults are retained unless a setting is required to obtain the common PCM format.
- Model IDs, voice IDs, transports, warmups, client location label, failures, and collection time are published.
- Provider ordering and plot colors are stable and neutral; no provider defines the baseline.

## Limitations

- One client and egress region cannot measure global routing performance.
- The benchmark exercises low load; concurrency limits, queueing, and tail behavior under load require a separate experiment.
- HTTP libraries may coalesce network reads, while WebSocket APIs expose message frames. The benchmark measures application-visible delivery, not packet-level timing or model-internal token cadence.
- The models use different voices and generate different utterance durations. PCM media-time normalization makes buffer replay meaningful but does not control voice quality or speaking style.
- No listening test, transcription score, or naturalness metric is included. Fast, smooth delivery can still contain poor speech.
- Provider services and aliases evolve. Dated snapshots are used when available, and every run must record exact model strings.
- Six prompts support an engineering teardown, not population-wide claims. Broader languages, domains, networks, and times of day should precede a production procurement decision.
- The local audio device, downstream WebRTC/Twilio transport, resampling, and operating-system scheduler are outside this API-to-client boundary.
- The controlled receive-pause replay is a sensitivity analysis over recorded traces, not a live impaired-network experiment. A separate traffic-shaped run is required to measure how providers and transports respond to real congestion and packet loss.
