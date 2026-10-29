#!/usr/bin/env python3
"""Render only measured JSON observations from benchmark_padded_reuse."""
import argparse
import csv
import json
from pathlib import Path
import re
import statistics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    rows = []
    for line in args.log.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.search(r'\{"sample":.*\}', line)
        if match:
            row = json.loads(match.group())
            if {"sample", "reused", "iterations", "elapsed_ms", "scratch_bytes"} <= row.keys():
                row["us_per_fill"] = row["elapsed_ms"] * 1000 / row["iterations"]
                rows.append(row)
    assert len(rows) == 18, f"expected 18 observations, got {len(rows)}"
    modes = {mode: sorted((r for r in rows if r["reused"] is mode), key=lambda r: r["sample"])
             for mode in (False, True)}
    for mode, samples in modes.items():
        assert [r["sample"] for r in samples] == list(range(9)), (mode, samples)
        assert all(r["iterations"] == 4096 and r["elapsed_ms"] > 0 for r in samples)
    assert len({r["scratch_bytes"] for r in rows}) == 1
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "scratch-observations.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {}
    for mode, samples in modes.items():
        values = [r["us_per_fill"] for r in samples]
        summary["reused" if mode else "fresh"] = {
            "samples": len(values), "iterations_per_sample": 4096,
            "median_us_per_fill": statistics.median(values),
            "min_us_per_fill": min(values), "max_us_per_fill": max(values),
        }
    summary["median_change_percent"] = (
        summary["reused"]["median_us_per_fill"] / summary["fresh"]["median_us_per_fill"] - 1
    ) * 100
    summary["scratch_bytes"] = rows[0]["scratch_bytes"]
    summary["scope"] = (
        "Isolated padded block/light reads only; fresh and retained scratch paths in the same branch. "
        "Not origin/main A/B, not whole-mesher timings, and not FPS. No significance claim."
    )
    (args.out / "scratch-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, ax = plt.subplots(figsize=(8.2, 5.2))
    colors = {False: "#596575", True: "#078b80"}
    for fresh, reused in zip(modes[False], modes[True]):
        ax.plot([0, 1], [fresh["us_per_fill"], reused["us_per_fill"]], color="#d3dae1", lw=1, zorder=1)
    for x, mode in enumerate((False, True)):
        values = [r["us_per_fill"] for r in modes[mode]]
        ax.scatter([x] * len(values), values, color=colors[mode], s=34, alpha=0.85, zorder=3)
        median = statistics.median(values)
        ax.plot([x - .16, x + .16], [median, median], color=colors[mode], lw=3, zorder=4)
        ax.annotate(f"Median {median:.2f} µs", (x + .18, median), va="center", color=colors[mode])
    ax.set_xticks([0, 1], ["Fresh scratch per job", "Retained scratch"])
    ax.set_xlim(-.45, 1.85)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("µs per padding fill")
    ax.set_title("Section padding only: fresh vs retained buffers", loc="left", fontweight="bold", pad=16)
    ax.yaxis.grid(True, color="#e9edf1")
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.text(.1, .025,
             "9 samples × 4,096 fills after warmup; execution order alternates. Lines pair sample numbers.\n"
             "Same-branch microbenchmark; excludes full meshing, GPU upload and frame scheduling. Not FPS.",
             fontsize=9, color="#46525f")
    fig.tight_layout(rect=[0, .12, 1, 1])
    fig.savefig(args.out / "mesh-scratch-stage.png", dpi=180)
    fig.savefig(args.out / "mesh-scratch-stage.svg")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
