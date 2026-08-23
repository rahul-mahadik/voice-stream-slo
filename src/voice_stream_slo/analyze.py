"""Tables, uncertainty intervals, and publication plots for trace directories."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt

from voice_stream_slo.metrics import chunk_rows, stall_rows, trace_metric_rows
from voice_stream_slo.schema import Trace
from voice_stream_slo.stress import stress_replay_rows
from voice_stream_slo.trace_io import read_traces

plt.switch_backend("Agg")


SUMMARY_METRICS: dict[str, tuple[str, Callable[..., Any]]] = {
    "median_ttfa_ms": ("ttfa_ms", np.median),
    "median_delivery_rtf": ("delivery_rtf", np.median),
    "median_trace_p95_interarrival_ms": ("interarrival_p95_ms", np.median),
    "median_trace_p95_pacing_error_ms": ("pacing_error_p95_ms", np.median),
    "glitch_free_rate": ("glitch_free", np.mean),
    "mean_underruns_per_utterance": ("underrun_count", np.mean),
    "mean_total_stall_ms": ("total_stall_ms", np.mean),
    "median_trace_p95_recovery_ms": ("recovery_p95_ms", np.median),
    "median_actual_startup_buffer_ms": ("startup_buffer_ms", np.median),
}

STALL_COLUMNS = [
    "trace_id",
    "provider",
    "model",
    "prompt_id",
    "buffer_depth_ms",
    "stall_index",
    "stall_started_ms",
    "stall_recovered_ms",
    "recovery_ms",
]

FAILURE_COLUMNS = ["trace_id", "provider", "model", "prompt_id", "error"]

STRESS_COLUMNS = [
    "trace_id",
    "provider",
    "model",
    "prompt_id",
    "buffer_depth_ms",
    "pause_ms",
    "injection_audio_fraction",
    "glitch_free",
    "underrun_count",
    "total_stall_ms",
    "max_stall_ms",
]


def _hierarchical_bootstrap(
    group: pd.DataFrame,
    column: str,
    statistic: Callable[..., Any],
    rng: np.random.Generator,
    draws: int,
) -> tuple[float, float, float]:
    values = group[column].astype(float).to_numpy()
    estimate = float(statistic(values))
    prompt_arrays = [
        prompt_group[column].astype(float).to_numpy()
        for _, prompt_group in group.groupby("prompt_id", sort=False)
    ]
    prompt_count = len(prompt_arrays)
    trial_counts = {len(prompt_values) for prompt_values in prompt_arrays}

    if len(trial_counts) == 1:
        trial_count = trial_counts.pop()
        prompt_matrix = np.vstack(prompt_arrays)
        selected_prompts = rng.integers(0, prompt_count, size=(draws, prompt_count))
        selected_values = prompt_matrix[selected_prompts]
        within_indices = rng.integers(
            0,
            trial_count,
            size=(draws, prompt_count, trial_count),
        )
        resampled = np.take_along_axis(selected_values, within_indices, axis=2)
        samples = statistic(resampled.reshape(draws, -1), axis=1)
    else:
        samples = np.empty(draws)
        for index in range(draws):
            selected_prompts = rng.integers(0, prompt_count, size=prompt_count)
            sampled_values = [
                rng.choice(
                    prompt_arrays[prompt_index],
                    size=len(prompt_arrays[prompt_index]),
                    replace=True,
                )
                for prompt_index in selected_prompts
            ]
            samples[index] = statistic(np.concatenate(sampled_values))
    low, high = np.percentile(samples, [2.5, 97.5])
    return estimate, float(low), float(high)


def _wilson_rate_interval(values: pd.Series) -> tuple[float, float, float]:
    """Return an empirical rate and a two-sided 95% Wilson score interval."""

    observations = values.astype(bool).to_numpy()
    count = len(observations)
    if count == 0:
        raise ValueError("at least one observation is required")
    estimate = float(np.mean(observations))
    z = 1.959963984540054
    denominator = 1.0 + z**2 / count
    center = (estimate + z**2 / (2.0 * count)) / denominator
    radius = (
        z
        * np.sqrt(estimate * (1.0 - estimate) / count + z**2 / (4.0 * count**2))
        / denominator
    )
    return estimate, float(center - radius), float(center + radius)


def _hierarchical_rate_interval(
    group: pd.DataFrame,
    column: str,
    rng: np.random.Generator,
    draws: int,
) -> tuple[float, float, float]:
    """Combine prompt/trial resampling with a non-degenerate boundary interval."""

    estimate, bootstrap_low, bootstrap_high = _hierarchical_bootstrap(
        group,
        column,
        np.mean,
        rng,
        draws,
    )
    _, wilson_low, wilson_high = _wilson_rate_interval(group[column])
    return estimate, min(bootstrap_low, wilson_low), max(bootstrap_high, wilson_high)


def _summary_table(
    metrics: pd.DataFrame,
    traces: list[Trace],
    seed: int,
    draws: int = 2_000,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    rng = np.random.default_rng(seed)
    for (provider, depth_ms), group in metrics.groupby(["provider", "buffer_depth_ms"]):
        for metric, (column, statistic) in SUMMARY_METRICS.items():
            if metric == "glitch_free_rate":
                estimate, low, high = _hierarchical_rate_interval(
                    group, column, rng, draws
                )
            else:
                estimate, low, high = _hierarchical_bootstrap(
                    group, column, statistic, rng, draws
                )
            rows.append(
                {
                    "provider": provider,
                    "buffer_depth_ms": depth_ms,
                    "metric": metric,
                    "estimate": estimate,
                    "ci_low": low,
                    "ci_high": high,
                    "n_traces": len(group),
                    "n_prompts": group["prompt_id"].nunique(),
                }
            )

    attempts = pd.DataFrame(
        {
            "trace_id": trace.trace_id,
            "provider": trace.provider,
            "prompt_id": trace.prompt_id,
            "request_success": trace.success,
        }
        for trace in traces
    )
    for depth_ms in sorted(metrics["buffer_depth_ms"].unique()):
        at_depth = metrics.loc[
            metrics["buffer_depth_ms"] == depth_ms,
            ["trace_id", "glitch_free"],
        ]
        outcomes = attempts.merge(at_depth, on="trace_id", how="left")
        outcomes["glitch_free"] = outcomes["glitch_free"].fillna(False)
        outcomes["playable_success"] = outcomes["request_success"] & outcomes["glitch_free"]
        for provider, group in outcomes.groupby("provider"):
            for metric, column in (
                ("request_success_rate", "request_success"),
                ("playable_success_rate", "playable_success"),
            ):
                estimate, low, high = _hierarchical_rate_interval(
                    group, column, rng, draws
                )
                rows.append(
                    {
                        "provider": provider,
                        "buffer_depth_ms": depth_ms,
                        "metric": metric,
                        "estimate": estimate,
                        "ci_low": low,
                        "ci_high": high,
                        "n_traces": len(group),
                        "n_prompts": group["prompt_id"].nunique(),
                    }
                )
    return pd.DataFrame(rows)


def _stress_summary(
    stress: pd.DataFrame,
    seed: int,
    draws: int = 2_000,
) -> pd.DataFrame:
    """Summarize strict survival across every declared injection location."""

    per_trace = (
        stress.groupby(
            ["trace_id", "provider", "prompt_id", "buffer_depth_ms", "pause_ms"],
            as_index=False,
        )["glitch_free"]
        .all()
        .rename(columns={"glitch_free": "all_positions_glitch_free"})
    )
    rows: list[dict[str, Any]] = []
    rng = np.random.default_rng(seed)
    for (provider, depth_ms, pause_ms), group in per_trace.groupby(
        ["provider", "buffer_depth_ms", "pause_ms"]
    ):
        estimate, low, high = _hierarchical_rate_interval(
            group,
            "all_positions_glitch_free",
            rng,
            draws,
        )
        rows.append(
            {
                "provider": provider,
                "buffer_depth_ms": depth_ms,
                "pause_ms": pause_ms,
                "all_positions_success_rate": estimate,
                "ci_low": low,
                "ci_high": high,
                "n_traces": len(group),
                "n_prompts": group["prompt_id"].nunique(),
            }
        )
    return pd.DataFrame(rows)


def _colors(providers: list[str]) -> dict[str, Any]:
    palette = plt.get_cmap("tab10")
    return {provider: palette(index) for index, provider in enumerate(sorted(providers))}


def _ecdf(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ordered = np.sort(values.astype(float))
    return ordered, np.arange(1, len(ordered) + 1) / len(ordered)


def _plot_pacing(chunks: pd.DataFrame, figure_dir: Path, colors: dict[str, Any]) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.8))
    data = chunks[chunks["sequence"] > 0]
    for provider, group in data.groupby("provider"):
        x, y = _ecdf(group["pacing_error_ms"].to_numpy())
        ax.plot(x, y, label=provider, color=colors[provider], linewidth=2)
    ax.axvline(0, color="#555555", linestyle="--", linewidth=1)
    ax.set_xlabel("Arrival gap minus preceding playable audio (ms)")
    ax.set_ylabel("Empirical CDF")
    ax.set_title("Client-observed inter-chunk pacing pressure")
    ax.legend(frameon=False)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(figure_dir / "pacing_error_ecdf.png", dpi=180)
    plt.close(fig)


def _plot_underruns(summary: pd.DataFrame, figure_dir: Path, colors: dict[str, Any]) -> None:
    data = summary[summary["metric"] == "mean_underruns_per_utterance"]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for provider, group in data.groupby("provider"):
        ordered = group.sort_values("buffer_depth_ms")
        x = ordered["buffer_depth_ms"].to_numpy()
        y = ordered["estimate"].to_numpy()
        ax.plot(x, y, marker="o", label=provider, color=colors[provider], linewidth=2)
        ax.fill_between(
            x,
            ordered["ci_low"].to_numpy(),
            ordered["ci_high"].to_numpy(),
            color=colors[provider],
            alpha=0.14,
        )
    ax.set_xlabel("Initial jitter-buffer depth (ms)")
    ax.set_ylabel("Mean underruns per utterance")
    if float(data["estimate"].max()) == 0.0:
        ax.set_ylim(-0.002, 0.05)
        ax.text(
            0.5,
            0.52,
            "No baseline underruns observed",
            transform=ax.transAxes,
            ha="center",
            va="center",
        )
    ax.set_title("Observed buffer-depth sensitivity")
    ax.legend(frameon=False)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(figure_dir / "underruns_by_buffer.png", dpi=180)
    plt.close(fig)


def _plot_ttfa_reliability(
    summary: pd.DataFrame,
    figure_dir: Path,
    colors: dict[str, Any],
    comparison_depth_ms: float,
) -> None:
    depth = summary[summary["buffer_depth_ms"] == comparison_depth_ms]
    ttfa = depth[depth["metric"] == "median_ttfa_ms"].set_index("provider")
    reliable = depth[depth["metric"] == "playable_success_rate"].set_index("provider")
    fig, ax = plt.subplots(figsize=(7, 5.2))
    x_values = ttfa["estimate"].astype(float)
    midpoint = (float(x_values.min()) + float(x_values.max())) / 2.0
    x_span = max(float(x_values.max()) - float(x_values.min()), 1.0)
    placed_labels: list[tuple[float, float, int]] = []
    for provider in x_values.sort_values().index:
        x = float(ttfa.loc[provider, "estimate"])
        y = float(reliable.loc[provider, "estimate"])
        x_low = x - float(ttfa.loc[provider, "ci_low"])
        x_high = float(ttfa.loc[provider, "ci_high"]) - x
        ax.errorbar(
            x,
            y,
            xerr=[[x_low], [x_high]],
            yerr=[
                [y - float(reliable.loc[provider, "ci_low"])],
                [float(reliable.loc[provider, "ci_high"]) - y],
            ],
            fmt="o",
            color=colors[provider],
            capsize=3,
        )
        horizontal_offset = -6 if x > midpoint else 6
        vertical_offset = -16 if y > 0.9 else 5
        while any(
            abs(x - previous_x) < 0.15 * x_span
            and abs(y - previous_y) < 0.08
            and vertical_offset == previous_offset
            for previous_x, previous_y, previous_offset in placed_labels
        ):
            vertical_offset -= 16
        placed_labels.append((x, y, vertical_offset))
        ax.annotate(
            provider,
            (x, y),
            xytext=(horizontal_offset, vertical_offset),
            textcoords="offset points",
            ha="right" if horizontal_offset < 0 else "left",
        )
    ax.set_xlabel("Median time to first audio (ms)")
    ax.set_ylabel(f"Playable-success rate ({comparison_depth_ms:g} ms buffer)")
    ax.set_xlim(float(x_values.min()) - 8, float(x_values.max()) + 8)
    ax.set_ylim(-0.06, 1.06)
    ax.set_title("Starting quickly is not the same as staying playable")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(figure_dir / "ttfa_vs_glitch_free.png", dpi=180)
    plt.close(fig)


def _plot_recovery(
    stalls: pd.DataFrame,
    figure_dir: Path,
    colors: dict[str, Any],
    comparison_depth_ms: float,
) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.8))
    data = stalls.loc[stalls["buffer_depth_ms"] == comparison_depth_ms]
    if data.empty:
        ax.text(0.5, 0.5, "No underruns at this buffer depth", ha="center", va="center")
    else:
        for provider, group in data.groupby("provider"):
            x, y = _ecdf(group["recovery_ms"].to_numpy())
            ax.plot(x, y, label=provider, color=colors[provider], linewidth=2)
        ax.legend(frameon=False)
    ax.set_xlabel("Time from starvation to next playable chunk (ms)")
    ax.set_ylabel("Empirical CDF")
    ax.set_title(f"Recovery behavior at a {comparison_depth_ms:g} ms buffer")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(figure_dir / "recovery_ecdf.png", dpi=180)
    plt.close(fig)


def _plot_stress_replay(
    stress_summary: pd.DataFrame,
    figure_dir: Path,
    colors: dict[str, Any],
) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for provider, group in stress_summary.groupby("provider"):
        ordered = group.sort_values("pause_ms")
        x = ordered["pause_ms"].to_numpy()
        y = ordered["all_positions_success_rate"].to_numpy()
        ax.plot(x, y, marker="o", label=provider, color=colors[provider], linewidth=2)
        ax.fill_between(
            x,
            ordered["ci_low"].to_numpy(),
            ordered["ci_high"].to_numpy(),
            color=colors[provider],
            alpha=0.14,
        )
    depth_ms = float(stress_summary["buffer_depth_ms"].iloc[0])
    ax.set_xlabel("Injected downstream receive pause (ms)")
    ax.set_ylabel("Traces surviving all three injection locations")
    ax.set_ylim(-0.03, 1.03)
    ax.set_title(f"Controlled delivery-pause replay ({depth_ms:g} ms buffer)")
    ax.legend(frameon=False)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(figure_dir / "stress_pause_curve.png", dpi=180)
    plt.close(fig)


def _plot_prefix_rtf(chunks: pd.DataFrame, figure_dir: Path, colors: dict[str, Any]) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.8))
    grid = np.linspace(0.05, 1.0, 80)
    for provider, provider_rows in chunks.groupby("provider"):
        curves: list[np.ndarray] = []
        for _, trace_rows in provider_rows.groupby("trace_id"):
            ordered = trace_rows.sort_values("utterance_progress")
            x = ordered["utterance_progress"].to_numpy()
            y = ordered["cumulative_delivery_rtf"].to_numpy()
            curves.append(np.interp(grid, x, y, left=y[0], right=y[-1]))
        matrix = np.vstack(curves)
        median = np.median(matrix, axis=0)
        low, high = np.percentile(matrix, [10, 90], axis=0)
        ax.plot(grid, median, label=provider, color=colors[provider], linewidth=2)
        ax.fill_between(grid, low, high, color=colors[provider], alpha=0.14)
    ax.axhline(1.0, color="#555555", linestyle="--", linewidth=1)
    ax.set_xlabel("Fraction of utterance audio delivered")
    ax.set_ylabel("Cumulative delivery RTF")
    ax.set_title("Delivery rate over the utterance (median and 10–90% band)")
    ax.legend(frameon=False)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(figure_dir / "rtf_over_utterance.png", dpi=180)
    plt.close(fig)


def _write_report(
    traces: list[Trace],
    summary: pd.DataFrame,
    output: Path,
    comparison_depth_ms: float,
    synthetic: bool,
    stress_summary: pd.DataFrame | None,
) -> None:
    providers = sorted({trace.provider for trace in traces if trace.success})
    lines = [
        "# Streaming TTS reliability results",
        "",
        (
            "This is a synthetic validation of the metric implementation; the labels below are "
            "controlled pacing scenarios, not TTS providers."
            if synthetic
            else "These results summarize client-observed PCM delivery from the declared live run."
        ),
        "",
        f"Comparison buffer: **{comparison_depth_ms:g} ms**. Continuous/count intervals use "
        "a hierarchical prompt/trial bootstrap; binary rates include the 95% Wilson envelope.",
        "",
        "| Provider/scenario | Median TTFA (ms) | Playable-success rate | "
        "Mean underruns | Median delivery RTF | Actual startup buffer (ms) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    depth = summary[summary["buffer_depth_ms"] == comparison_depth_ms]
    for provider in providers:
        values = depth[depth["provider"] == provider].set_index("metric")["estimate"]
        lines.append(
            f"| {provider} | {values['median_ttfa_ms']:.1f} | "
            f"{values['playable_success_rate']:.1%} | "
            f"{values['mean_underruns_per_utterance']:.2f} | "
            f"{values['median_delivery_rtf']:.3f} | "
            f"{values['median_actual_startup_buffer_ms']:.1f} |"
        )
    if stress_summary is not None:
        headline_pause_ms = min(
            stress_summary["pause_ms"].unique(),
            key=lambda value: abs(float(value) - 400.0),
        )
        headline = stress_summary[stress_summary["pause_ms"] == headline_pause_ms]
        lines.extend(
            [
                "",
                "## Controlled downstream pause replay",
                "",
                "This is a counterfactual replay of the recorded traces, not an observed "
                "provider outage. A receive pause is injected at 25%, 50%, and 75% of "
                "each utterance; a trace passes only if all three locations remain playable.",
                "",
                f"| Provider/scenario | Survives a {headline_pause_ms:g} ms pause | 95% CI |",
                "|---|---:|---:|",
            ]
        )
        for provider in providers:
            row = headline[headline["provider"] == provider].iloc[0]
            lines.append(
                f"| {provider} | {row['all_positions_success_rate']:.1%} | "
                f"{row['ci_low']:.1%}–{row['ci_high']:.1%} |"
            )
    lines.extend(
        [
            "",
            "TTFA and continuous playout answer different questions. Inspect the "
            "buffer-depth curve, "
            "pacing-error distribution, recovery distribution, and prefix RTF trajectory together.",
            "",
            "See `tables/summary_long.csv` for estimates and confidence intervals "
            "and `../raw/` for "
            "the auditable receive-event traces.",
        ]
    )
    (output / "report.md").write_text("\n".join(lines) + "\n")


def analyze(
    trace_root: str | Path,
    destination: str | Path,
    buffer_depths_ms: list[float],
    seed: int,
    synthetic: bool = False,
    stress_replay: dict[str, Any] | None = None,
) -> dict[str, int]:
    traces = read_traces(trace_root)
    successful = [trace for trace in traces if trace.success]
    if not successful:
        raise ValueError("no successful traces found")

    output = Path(destination)
    table_dir = output / "tables"
    figure_dir = output / "figures"
    table_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)

    metrics = pd.DataFrame(
        row for trace in successful for row in trace_metric_rows(trace, buffer_depths_ms)
    )
    chunks = pd.DataFrame(row for trace in successful for row in chunk_rows(trace))
    stalls = pd.DataFrame(
        (row for trace in successful for row in stall_rows(trace, buffer_depths_ms)),
        columns=STALL_COLUMNS,
    )
    failures = pd.DataFrame(
        (
            {
                "trace_id": trace.trace_id,
                "provider": trace.provider,
                "model": trace.model,
                "prompt_id": trace.prompt_id,
                "error": trace.error,
            }
            for trace in traces
            if not trace.success
        ),
        columns=FAILURE_COLUMNS,
    )
    summary = _summary_table(metrics, traces, seed)
    stress = None
    stress_summary = None
    if stress_replay:
        stress = pd.DataFrame(
            (
                row
                for trace in successful
                for row in stress_replay_rows(
                    trace,
                    float(stress_replay["buffer_depth_ms"]),
                    [float(value) for value in stress_replay["pause_durations_ms"]],
                    [
                        float(value)
                        for value in stress_replay["injection_audio_fractions"]
                    ],
                )
            ),
            columns=STRESS_COLUMNS,
        )
        stress_summary = _stress_summary(stress, seed)

    metrics.to_csv(table_dir / "trace_metrics.csv", index=False)
    chunks.to_csv(table_dir / "chunk_metrics.csv", index=False)
    stalls.to_csv(table_dir / "stall_events.csv", index=False)
    failures.to_csv(table_dir / "failures.csv", index=False)
    summary.to_csv(table_dir / "summary_long.csv", index=False)
    if stress is not None and stress_summary is not None:
        stress.to_csv(table_dir / "stress_replay.csv", index=False)
        stress_summary.to_csv(table_dir / "stress_summary.csv", index=False)

    providers = sorted(metrics["provider"].unique().tolist())
    colors = _colors(providers)
    comparison_depth_ms = min(buffer_depths_ms, key=lambda value: abs(value - 80.0))
    _plot_pacing(chunks, figure_dir, colors)
    _plot_underruns(summary, figure_dir, colors)
    _plot_ttfa_reliability(summary, figure_dir, colors, comparison_depth_ms)
    _plot_recovery(stalls, figure_dir, colors, comparison_depth_ms)
    _plot_prefix_rtf(chunks, figure_dir, colors)
    if stress_summary is not None:
        _plot_stress_replay(stress_summary, figure_dir, colors)
    _write_report(
        successful,
        summary,
        output,
        comparison_depth_ms,
        synthetic,
        stress_summary,
    )

    run_summary = {
        "successful_traces": len(successful),
        "failed_traces": len(traces) - len(successful),
        "providers_or_scenarios": providers,
        "buffer_depths_ms": buffer_depths_ms,
        "comparison_depth_ms": comparison_depth_ms,
        "synthetic": synthetic,
        "stress_replay": stress_replay,
    }
    (output / "summary.json").write_text(json.dumps(run_summary, indent=2) + "\n")
    return {"success": len(successful), "failure": len(traces) - len(successful)}
