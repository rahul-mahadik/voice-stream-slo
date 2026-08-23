# Streaming TTS reliability results

These results summarize client-observed PCM delivery from the declared live run.

Comparison buffer: **80 ms**. Continuous/count intervals use a hierarchical prompt/trial bootstrap; binary rates include the 95% Wilson envelope.

| Provider/scenario | Median TTFA (ms) | Playable-success rate | Mean underruns | Median delivery RTF | Actual startup buffer (ms) |
|---|---:|---:|---:|---:|---:|
| cartesia | 91.4 | 100.0% | 0.00 | 0.118 | 154.0 |
| deepgram | 93.2 | 100.0% | 0.00 | 0.614 | 154.0 |
| elevenlabs | 195.2 | 100.0% | 0.00 | 0.059 | 92.1 |

## Controlled downstream pause replay

This is a counterfactual replay of the recorded traces, not an observed provider outage. A receive pause is injected at 25%, 50%, and 75% of each utterance; a trace passes only if all three locations remain playable.

| Provider/scenario | Survives a 400 ms pause | 95% CI |
|---|---:|---:|
| cartesia | 90.8% | 71.7%–100.0% |
| deepgram | 66.7% | 33.3%–100.0% |
| elevenlabs | 100.0% | 96.9%–100.0% |

TTFA and continuous playout answer different questions. Inspect the buffer-depth curve, pacing-error distribution, recovery distribution, and prefix RTF trajectory together.

See `tables/summary_long.csv` for estimates and confidence intervals and `../raw/` for the auditable receive-event traces.
