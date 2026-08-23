import json
from datetime import UTC, datetime

import pandas as pd

from voice_stream_slo.analyze import analyze
from voice_stream_slo.schema import AudioSpec, ChunkEvent, Trace
from voice_stream_slo.synthetic import write_synthetic_traces
from voice_stream_slo.trace_io import write_trace


def test_synthetic_demo_proves_ttfa_is_not_reliability(tmp_path) -> None:
    prompts = [{"id": "p1", "length": "short", "text": "A short test prompt."}]
    raw = tmp_path / "raw" / "traces"
    write_synthetic_traces(prompts, raw, AudioSpec(), repetitions=4, seed=7)
    output = tmp_path / "analysis"
    counts = analyze(raw, output, [0.0, 40.0, 80.0, 120.0], seed=7, synthetic=True)

    assert counts == {"success": 12, "failure": 0}
    summary = pd.read_csv(output / "tables" / "summary_long.csv")
    depth = summary[summary["buffer_depth_ms"] == 80]
    ttfa = depth[depth["metric"] == "median_ttfa_ms"].set_index("provider")["estimate"]
    underruns = depth[
        depth["metric"] == "mean_underruns_per_utterance"
    ].set_index("provider")["estimate"]
    assert abs(ttfa["steady"] - ttfa["bursty_same_ttfa"]) < 15
    assert underruns["bursty_same_ttfa"] > underruns["steady"]
    assert json.loads((output / "summary.json").read_text())["synthetic"] is True
    assert (output / "figures" / "ttfa_vs_glitch_free.png").exists()


def test_analysis_handles_a_run_with_no_stalls(tmp_path) -> None:
    raw = tmp_path / "raw" / "traces"
    trace = Trace.create(
        trace_id="steady-p1-r000",
        provider="steady",
        model="fixture-v1",
        voice="fixture",
        prompt_id="p1",
        text="A short test prompt.",
        started_at_utc=datetime.now(UTC).isoformat(),
        transport="fixture",
        connection_reused=True,
        connection_setup_ms=0.0,
        audio=AudioSpec(),
        chunks=[
            ChunkEvent(
                sequence=index,
                arrival_ms=100.0 + index * 20.0,
                size_bytes=1_920,
                media_duration_ms=40.0,
            )
            for index in range(5)
        ],
        completed_ms=185.0,
    )
    write_trace(trace, raw / "steady" / "steady-p1-r000.json")

    output = tmp_path / "analysis"
    counts = analyze(
        raw,
        output,
        [0.0, 40.0, 80.0],
        seed=7,
        stress_replay={
            "buffer_depth_ms": 80.0,
            "pause_durations_ms": [0.0, 200.0],
            "injection_audio_fractions": [0.25, 0.5, 0.75],
        },
    )

    assert counts == {"success": 1, "failure": 0}
    stalls = pd.read_csv(output / "tables" / "stall_events.csv")
    assert stalls.empty
    assert "buffer_depth_ms" in stalls.columns
    assert (output / "figures" / "recovery_ecdf.png").exists()
    stress = pd.read_csv(output / "tables" / "stress_summary.csv")
    assert set(stress["pause_ms"]) == {0.0, 200.0}
    assert (output / "figures" / "stress_pause_curve.png").exists()
