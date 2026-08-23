# Streaming TTS reliability results

This is a synthetic validation of the metric implementation; the labels below are controlled pacing scenarios, not TTS providers.

Comparison buffer: **80 ms**. Bootstrap intervals are trace-level 95% intervals.

| Provider/scenario | Median TTFA (ms) | Playable-success rate | Mean underruns | Median delivery RTF |
|---|---:|---:|---:|---:|
| bursty_same_ttfa | 124.0 | 0.0% | 2.77 | 1.142 |
| late_but_steady | 220.0 | 100.0% | 0.00 | 1.081 |
| steady | 124.6 | 100.0% | 0.00 | 0.966 |

TTFA and continuous playout answer different questions. Inspect the buffer-depth curve, pacing-error distribution, recovery distribution, and prefix RTF trajectory together.

See `tables/summary_long.csv` for estimates and confidence intervals and `../raw/` for the auditable receive-event traces.
