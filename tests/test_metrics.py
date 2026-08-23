from datetime import UTC, datetime

import pytest

from voice_stream_slo.metrics import chunk_rows, trace_metric_rows
from voice_stream_slo.schema import AudioSpec, ChunkEvent, Trace


def _trace(arrivals: list[float]) -> Trace:
    audio = AudioSpec()
    return Trace.create(
        trace_id="trace",
        provider="fixture",
        model="fixture-v1",
        voice="voice",
        prompt_id="prompt",
        text="test prompt",
        started_at_utc=datetime.now(UTC).isoformat(),
        transport="fixture",
        connection_reused=True,
        connection_setup_ms=0.0,
        audio=audio,
        chunks=[ChunkEvent(index, arrival, 1_920, 40.0) for index, arrival in enumerate(arrivals)],
        completed_ms=arrivals[-1] + 5.0,
    )


def test_pacing_error_normalizes_arrival_gap_by_audio_duration() -> None:
    rows = chunk_rows(_trace([100.0, 130.0, 200.0]))
    assert rows[1]["pacing_error_ms"] == pytest.approx(-10.0)
    assert rows[2]["pacing_error_ms"] == pytest.approx(30.0)


def test_same_ttfa_can_have_different_playout_reliability() -> None:
    smooth = trace_metric_rows(_trace([100.0, 130.0, 160.0, 190.0]), [0])[0]
    bursty = trace_metric_rows(_trace([100.0, 130.0, 250.0, 280.0]), [0])[0]
    assert smooth["ttfa_ms"] == bursty["ttfa_ms"]
    assert smooth["underrun_count"] < bursty["underrun_count"]
    assert smooth["pacing_error_max_ms"] < bursty["pacing_error_max_ms"]


def test_delivery_rtf_includes_time_to_first_audio() -> None:
    row = trace_metric_rows(_trace([100.0, 130.0, 160.0, 190.0]), [80])[0]
    assert row["audio_ms"] == pytest.approx(160.0)
    assert row["delivery_rtf"] == pytest.approx(190.0 / 160.0)
