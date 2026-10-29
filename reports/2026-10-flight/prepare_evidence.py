#!/usr/bin/env python3
"""Whitelist benchmark metrics and redraw the public evidence figures.

Requires Python 3.10+ and matplotlib. No game process is started by this script.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path


VARIANTS = {
    "stock": "Stock",
    "segment": "SegmentHeap manifest only",
    "final": "Combined changes (matched phase)",
    "sustained": "Combined changes (separate extended run)",
}
RENDERER_FIELDS = (
    "resident_sections", "arena_bytes", "section_vertex_bytes", "drawn_sections",
    "section_draw_calls", "gpu_allocated_bytes", "gpu_reserved_bytes",
)
LOD_FIELDS = (
    "resident_quads", "active_tiles", "cached_tiles", "target_tiles",
    "sampled_target_tiles", "pending_observations", "refined_samples",
)


def percentile(values, fraction):
    """Nearest rank, matching the previously recorded aggregate report."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def aggregate(rows):
    values = [x for row in rows for x in row["frame_ms"]]
    seconds = math.fsum(values) / 1000
    return {
        "frames": len(values), "seconds": seconds,
        "average_fps": len(values) / seconds,
        "p50_ms": percentile(values, .50), "p95_ms": percentile(values, .95),
        "p99_ms": percentile(values, .99), "max_ms": max(values),
        "frames_over_16_67_ms": sum(x > 1000 / 60 for x in values),
        "frames_over_25_ms": sum(x > 25 for x in values),
    }


def metric_status(raw, zero, label):
    result = {
        "point": label,
        "seconds_after_warmup": raw["uptime_seconds"] - zero,
        "renderer": {key: raw["renderer"][key] for key in RENDERER_FIELDS},
        "lod": {key: raw["lod"][key] for key in LOD_FIELDS},
    }
    for key in ("chunks", "pending_chunks", "pending_uploads"):
        result[key] = raw[key]
    return result


def sanitize(input_dir, output):
    variants = {}
    for key, label in VARIANTS.items():
        source = json.loads((input_dir / f"fix-bench-{key}.json").read_text("utf-8-sig"))
        zero = source["warm_status"]["uptime_seconds"]
        statuses = [metric_status(source["warm_status"], zero, "end_of_rd64_warmup"),
                    metric_status(source["settled_status"], zero, "end_of_rd16_settle")]
        rows = []
        for index, row in enumerate(source["passes"]):
            summary = row["summary"]
            arrays = {name: summary[name] for name in ("frame_ms", "cpu_ms", "gpu_ms")}
            if not arrays["frame_ms"] or any(
                not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0
                for values in arrays.values() for x in values
            ):
                raise ValueError(f"Invalid numeric samples in {key}, pass {index + 1}")
            if len(arrays["frame_ms"]) != summary["frames"]:
                raise ValueError(f"Frame count mismatch in {key}, pass {index + 1}")
            clean = {"pass": index + 1, "direction": "out" if index % 2 == 0 else "back",
                     "phase": "late" if key == "sustained" and index >= 4 else "initial",
                     "before": metric_status(row["before"], zero, "before_flight"),
                     "after": metric_status(row["after"], zero, "after_flight"), **arrays}
            clean["aggregate"] = aggregate([clean])
            rows.append(clean)
            statuses.append(clean["after"])
        if "post_settled_status" in source:
            statuses.append(metric_status(source["post_settled_status"], zero, "end_of_extra_settle"))
        statuses.append(metric_status(source["final_status"], zero, "final"))
        statuses.sort(key=lambda status: status["seconds_after_warmup"])
        variants[key] = {"label": label, "passes": rows, "status_samples": statuses,
                         "aggregate_initial": aggregate(rows[:4])}
        if key == "sustained":
            variants[key]["aggregate_late"] = aggregate(rows[4:])

    data = {
        "schema_version": 1,
        "base_commit": "baa379d71777f06a95b4e7650b2209a3d4209033",
        "current_pr_base_was_not_benchmarked": "bd665f28a",
        "hardware": {"os": "Windows 11", "cpu": "Intel Core i9-13900K",
                     "gpu": "NVIDIA GeForce RTX 3090", "resolution": [2560, 1440],
                     "backend": "Vulkan", "monitor_hz": 165},
        "protocol": {"runs_per_variant": 1, "initial_passes": 4, "flight_blocks": 256,
                     "flight_seconds": 8, "initial_settle_seconds": 5,
                     "warm_render_distance": 64, "warm_seconds": 20,
                     "measured_render_distance": 16, "settle_seconds": 12,
                     "simulation_distance": 9, "lod_distance": 64, "lod_detail": "full",
                     "worker_setting": 0, "observed_worker_threads": 31,
                     "initial_max_fps": 160, "in_game_vsync": False,
                     "nvidia_global_vsync": "forced on (read-only driver inspection)",
                     "extended_settle_seconds": 45, "extended_passes": 8,
                     "extended_max_fps_option": 260,
                     "extended_option_meaning": "unlimited in this game",
                     "native_sampler_hz_initial_runs": 20,
                     "native_sampler_seconds_initial_runs": 15,
                     "native_sampler_used_in_sustained_run": False},
        "binary_sha256": {
            "stock": "9e6915e254fc3347190fcc4cd29bfcb97f54cb7bd730e7e41563f0ed29b63436",
            "segment": "7845b3646e635f2d9a88f16ac1360d01149de3ea9f846995bdd1936a42e3055e",
            "combined": "151524b630d42a0947871c7c6583c6a294b1efed788675d7e631760b9c311639",
        },
        "segment_binary_verification": {
            "manifest_added": True, "original_resources_preserved": True,
            "all_non_resource_sections_unchanged": True,
        },
        "heap_probe_context": {
            "separate_observation_from_frame_comparison": True,
            "sampling_hz": 20, "flight_samples": 242,
            "process_heap_lock_wait_samples": 112,
            "sample_fraction_percent": 112 / 242 * 100,
            "heap_realloc_verified_caller_samples": 65,
            "validated_import_chain": ["kernel32.dll!GetProcessHeap", "kernel32.dll!HeapReAlloc"],
            "matching_pdb_available_for_stock": False,
            "exact_rust_function_identified": False,
            "max_suspended_ms": 0.36530010402202606,
            "average_suspended_ms": 0.13266610893736447,
            "interpretation": "Sampled main-thread wall-time occupancy; not exact frame cost or causal attribution.",
        },
        "variants": variants,
    }
    output.write_bytes((json.dumps(data, ensure_ascii=True, indent=2) + "\n").encode("utf-8"))
    return data


def plot(data, output_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "axes.grid": True,
                         "grid.alpha": .20, "grid.linewidth": .6,
                         "figure.facecolor": "white", "savefig.facecolor": "white"})
    palette = {"stock": "#b7472a", "segment": "#176797", "final": "#176797", "sustained": "#2a7c55"}

    def save(fig, stem):
        fig.savefig(output_dir / f"{stem}.png", dpi=180, bbox_inches="tight",
                    metadata={"Software": "matplotlib"})
        fig.savefig(output_dir / f"{stem}.svg", bbox_inches="tight",
                    metadata={"Date": None, "Creator": "matplotlib"})
        plt.close(fig)

    def comparison(other, stem, title, subtitle):
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.8), gridspec_kw={"width_ratios": [1.5, 1]})
        fig.text(.075, 1.02, title, fontsize=15, weight="bold", ha="left", va="top")
        fig.text(.075, .955, subtitle, fontsize=10, color="#404040", va="top")
        table = []
        for key in ("stock", other):
            variant = data["variants"][key]
            values = sorted(x for row in variant["passes"][:4] for x in row["frame_ms"])
            # Strictly greater-than empirical tail probability, computed from all frames.
            axes[0].step(values, [(len(values) - i - 1) / len(values) for i in range(len(values))],
                         where="post", color=palette[key], lw=1.8, label=variant["label"])
            p99s = [row["aggregate"]["p99_ms"] for row in variant["passes"][:4]]
            axes[1].plot(range(1, 5), p99s, "o-", color=palette[key], lw=1.6,
                         label=variant["label"])
            metrics = variant["aggregate_initial"]
            table.append(f"{variant['label']}: {metrics['frames']:,} frames / {metrics['seconds']:.3f} s; "
                         f"{metrics['average_fps']:.2f} FPS; P99 {metrics['p99_ms']:.2f} ms; max {metrics['max_ms']:.2f} ms")
        axes[0].set(xlabel="Frame time (ms; lower is better)", ylabel="Fraction of frames above threshold",
                    xlim=(0, 60), ylim=(.0001, 1), yscale="log")
        axes[0].set_yticks([1, .1, .01, .001, .0001], ["100%", "10%", "1%", "0.1%", "0.01%"])
        axes[0].axvline(6.25, color="#666666", ls=":", lw=1)
        axes[0].text(6.8, .00018, "160 FPS = 6.25 ms", color="#555555", fontsize=8)
        axes[0].legend(frameon=False, fontsize=9, loc="upper right")
        axes[1].set(xlabel="Pass within the same run", ylabel="P99 frame time (ms)",
                    xticks=range(1, 5), xticklabels=["1 out", "2 back", "3 out", "4 back"], ylim=(0, 45))
        axes[1].set_title("Within-run variation", fontsize=11)
        fig.text(.075, -.035, "\n".join(table), fontsize=9, linespacing=1.55)
        fig.text(.075, -.14, "One machine, one run per variant; four passes are not independent replicate runs.\n"
                 "Same route/settings and 160 FPS game cap; geometry readiness can vary. No confidence interval or universal speedup is implied.",
                 fontsize=8.5, color="#404040", linespacing=1.45)
        fig.subplots_adjust(top=.80, bottom=.17, wspace=.30)
        save(fig, stem)

    comparison("segment", "segmentheap-frame-times", "SegmentHeap manifest-only comparison",
               "Same stock executable code; only the Windows heap manifest changed. Initial four-pass phase.")
    comparison("final", "combined-frame-times", "Combined changes: matched protocol phase",
               "Allocator, meshing and LOD changes together, with different build flags. This is not per-fix attribution.")

    fig, axes = plt.subplots(2, 2, figsize=(12, 6.4), sharex="col")
    fig.suptitle("Geometry residency after a render-distance reduction", x=.075, ha="left", fontsize=15, weight="bold", y=1.02)
    fig.text(.075, .975, "Context for the LOD retirement fix: these are combined builds, not an isolated LOD A/B test.", fontsize=10)
    for column, keys in enumerate((("stock", "final"), ("sustained",))):
        for key in keys:
            variant = data["variants"][key]
            points = variant["status_samples"]
            times = [p["seconds_after_warmup"] for p in points]
            axes[0, column].plot(times, [p["renderer"]["resident_sections"] / 1000 for p in points],
                                 "o-", color=palette[key], ms=3,
                                 label="Stock" if key == "stock" else "Combined changes")
            axes[1, column].plot(times, [p["lod"]["resident_quads"] / 1e6 for p in points],
                                 "o-", color=palette[key], ms=3)
        if column == 0:
            axes[0, column].legend(frameon=False, fontsize=8.5, loc="upper right")
        axes[0, column].set_ylim(0, 140)
        axes[1, column].set_ylim(0, 3.6)
        axes[1, column].set_xlabel("Seconds after end of RD64 warmup")
    axes[0, 0].set_title("Matched initial protocol (separate runs)", fontsize=11)
    axes[0, 1].set_title("Extended combined run (separate phase)", fontsize=11)
    axes[0, 0].set_ylabel("Resident full-detail sections (thousands)")
    axes[1, 0].set_ylabel("Resident LOD quads (millions)")
    axes[1, 0].set_xlim(-1, 47)
    axes[1, 1].set_xlim(-3, 158)
    extended = data["variants"]["sustained"]
    wait_start = extended["passes"][3]["after"]["seconds_after_warmup"]
    wait_end = next(p["seconds_after_warmup"] for p in extended["status_samples"] if p["point"] == "end_of_extra_settle")
    for ax in axes[:, 1]:
        ax.axvspan(wait_start, wait_end, color="#dedede", alpha=.6, zorder=-1)
        ax.axvline(wait_start, color="#777777", ls=":", lw=1)
    axes[0, 1].text(wait_start + 2, 118, "45 s extra settle\ncap option: 160 → 260\n(260 means unlimited)", fontsize=8, color="#444444")
    fig.text(.075, -.01, "RD64 warmup lasted 20 s; RD16 was then restored and allowed 12 s to settle before flight. Points are sparse status snapshots; lines guide the eye.\n"
             "The extended run includes a cap change and extra wait, and had no native sampler. Its late phase cannot be compared directly with stock throughput.",
             fontsize=8.5, linespacing=1.5, color="#404040")
    fig.subplots_adjust(top=.89, bottom=.15, hspace=.20, wspace=.26)
    save(fig, "lod-residency")

    fig, ax = plt.subplots(figsize=(11, 3.8))
    rows = extended["passes"]
    for i, row in enumerate(rows):
        # The status gives elapsed game time; frame durations provide the local trace.
        elapsed = row["before"]["seconds_after_warmup"]
        times = []
        for value in row["frame_ms"]:
            elapsed += value / 1000
            times.append(elapsed)
        ax.plot(times, row["frame_ms"], color="#176797" if i < 4 else "#2a7c55", lw=.35,
                label="Initial 4 passes (cap 160)" if i == 0 else "Late 8 passes (option 260 = unlimited)" if i == 4 else None)
    ax.axvspan(wait_start, wait_end, color="#dedede", alpha=.6)
    ax.axhline(1000 / 165, ls=":", lw=1.2, color="#444444", label="165 Hz interval (6.06 ms)")
    ax.set(xlabel="Seconds after end of RD64 warmup", ylabel="Frame time (ms)", ylim=(0, 35), xlim=(10, 157))
    ax.set_title("Extended combined run: late display-limited phase", loc="left", fontsize=14, pad=14)
    ax.text(wait_start + 2, 25, "Extra settle / cap change", fontsize=9, color="#555555")
    ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    late = extended["aggregate_late"]
    fig.text(.125, -.04, f"Late phase: {late['frames']:,} frames / {late['seconds']:.3f} s; {late['average_fps']:.2f} FPS; P99 {late['p99_ms']:.2f} ms; max {late['max_ms']:.2f} ms.\n"
             "165 Hz monitor; in-game VSync was off, but the NVIDIA global VSync setting was forced on. This plateau does not measure maximum hardware throughput.",
             fontsize=8.5, linespacing=1.5, color="#404040")
    fig.subplots_adjust(bottom=.2)
    save(fig, "sustained-frame-times")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, help="Directory containing the four private fix-bench-*.json files")
    parser.add_argument("--data", type=Path, help="Sanitized .json or .json.gz (defaults to the adjacent dataset)")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    default_data = Path(__file__).with_name("data.json.gz")
    if args.input_dir:
        data = sanitize(args.input_dir, args.data or args.output_dir / "data.json")
    else:
        data_path = args.data or (default_data if default_data.exists() else default_data.with_suffix(""))
        if data_path.suffix == ".gz":
            data = json.loads(gzip.decompress(data_path.read_bytes()).decode("utf-8"))
        else:
            data = json.loads(data_path.read_text("utf-8"))
    plot(data, args.output_dir)
    encoded = (json.dumps(data, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    # mtime=0 and no original filename make the archive deterministic and private-path free.
    with (args.output_dir / "data.json.gz").open("wb") as stream:
        with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as compressed:
            compressed.write(encoded)
    summary = {key: data[key] for key in ("schema_version", "base_commit", "current_pr_base_was_not_benchmarked", "hardware", "protocol")}
    summary["chart_source"] = {
        "data_json_sha256": hashlib.sha256(encoded).hexdigest(),
        "data_json_gz_sha256": hashlib.sha256((args.output_dir / "data.json.gz").read_bytes()).hexdigest(),
        "prepare_evidence_py_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    summary["aggregates"] = {key: {name: variant[name] for name in ("aggregate_initial", "aggregate_late") if name in variant}
                             for key, variant in data["variants"].items()}
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    print(json.dumps({key: {name: variant[name] for name in ("aggregate_initial", "aggregate_late") if name in variant}
                      for key, variant in data["variants"].items()}, indent=2))


if __name__ == "__main__":
    main()
