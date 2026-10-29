#!/usr/bin/env python3
"""Collect a fresh, sanitized benchmark in a separate game home.

This script is for reviewers' own local worlds and binaries. It never connects to
an existing game's control socket. It does not reproduce the native stack sampler.
Only whitelisted timing/residency data are written to --output; console logs and
the copied world remain in the newly created private scratch directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from prepare_evidence import aggregate, metric_status


def change_options(path, changes):
    lines = path.read_text("utf-8").splitlines() if path.exists() else []
    remaining = dict(changes)
    updated = []
    for line in lines:
        key = line.split(":", 1)[0]
        if key in changes:
            updated.append(f"{key}:{changes[key]}")
            remaining.pop(key, None)
        else:
            updated.append(line)
    updated.extend(f"{key}:{value}" for key, value in remaining.items())
    path.write_text("\n".join(updated) + "\n", "utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--ctl", type=Path, required=True)
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--world-source", type=Path, required=True)
    parser.add_argument("--settings-dir", type=Path, required=True,
                        help="Copy of options.txt, horizon-graphics.txt and horizon-extras.txt")
    parser.add_argument("--scratch-parent", type=Path, required=True,
                        help="Private location for the copied world and console logs")
    parser.add_argument("--output", type=Path, required=True,
                        help="Destination JSON containing only sanitized benchmark metrics")
    parser.add_argument("--variant", choices=("stock", "segment", "final", "sustained"), required=True)
    parser.add_argument("--start", nargs=3, type=float, required=True, metavar=("X", "Y", "Z"))
    parser.add_argument("--yaw", type=float, required=True)
    parser.add_argument("--pitch", type=float, required=True)
    args = parser.parse_args()
    game, ctl, resources = (p.resolve(strict=True) for p in (args.game, args.ctl, args.resources))
    world_source = args.world_source.resolve(strict=True)
    settings_dir = args.settings_dir.resolve(strict=True)
    args.scratch_parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="horizon-benchmark-", dir=args.scratch_parent.resolve()))
    socket = scratch / "control.json"
    world_name = "BenchmarkWorld"
    shutil.copytree(world_source, scratch / "saves" / world_name,
                    ignore=shutil.ignore_patterns("session.lock"))
    for filename in ("options.txt", "horizon-graphics.txt", "horizon-extras.txt"):
        shutil.copy2(settings_dir / filename, scratch / filename)
    change_options(scratch / "options.txt", {
        "pauseOnLostFocus": "false", "inactivityFpsLimit": '"minimized"',
        "fullscreen": "false", "maxFps": 160, "renderDistance": 16,
        "simulationDistance": 9, "enableVsync": "false",
    })
    change_options(scratch / "horizon-graphics.txt", {
        "graphicsApi": "vulkan", "workers": 0, "lodDistance": 64,
        "farDetail": "full", "chunkUpdates": 0,
    })
    change_options(scratch / "horizon-extras.txt", {"discordPresence": "false"})
    env = os.environ.copy()
    for key, folder in {
        "HORIZON_HOME": ".", "HORIZON_LAUNCHER_HOME": "launcher", "XDG_DATA_HOME": "data",
        "XDG_CONFIG_HOME": "config", "HORIZON_LAUNCHER_TRASH": "trash",
        "HORIZON_LAUNCHER_CLIPBOARD": "clipboard", "HORIZON_LAUNCHER_DESKTOP": "desktop",
    }.items():
        env[key] = str(scratch / folder)
    env.update(HORIZON_NO_AUDIO="1", HORIZON_LAUNCHER_NO_SELF_UPDATE="1", HORIZON_TELEMETRY_URL="off")

    def control(*words, timeout=60):
        completed = subprocess.run(
            [str(ctl), "--timeout", str(timeout), "--socket", str(socket), *map(str, words)],
            capture_output=True, text=True, encoding="utf-8", timeout=timeout + 5,
        )
        if completed.returncode or not completed.stdout.strip():
            # Do not put raw control output (which may contain world/player data) in the public JSON.
            raise RuntimeError("Control command failed; inspect the private scratch directory locally.")
        result = json.loads(completed.stdout)
        if "error" in result:
            raise RuntimeError("Control command returned an error; inspect it locally.")
        return result

    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = {"schema_version": 1, "variant": args.variant, "passes": [], "status_samples": [],
              "binary_sha256": hashlib.sha256(game.read_bytes()).hexdigest(),
              "native_sampler_used": False,
              "protocol": {"initial_settle_seconds": 5, "warm_render_distance": 64,
                           "warm_seconds": 20, "render_distance": 16, "settle_seconds": 12,
                           "flight_blocks": 256, "flight_seconds": 8, "initial_max_fps": 160,
                           "resolution": [2560, 1440], "simulation_distance": 9,
                           "lod_distance": 64, "worker_setting": 0},
              "complete": False}

    def save():
        args.output.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", "utf-8")

    proc = None
    with (scratch / "console.log").open("w", encoding="utf-8") as console:
        try:
            proc = subprocess.Popen(
                [str(game), "--resources", str(resources), "--world", world_name,
                 "--control-socket", str(socket), "--width", "2560", "--height", "1440"],
                cwd=scratch, env=env, stdout=console, stderr=subprocess.STDOUT,
            )
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError("Benchmark game exited; inspect the private console log.")
                if socket.exists():
                    try:
                        state = control("state", timeout=2)
                        if state.get("player") and state.get("screen") == "playing":
                            break
                    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError):
                        pass
                time.sleep(.5)
            else:
                raise TimeoutError("The isolated game did not enter its playing state in 90 seconds.")
            control("tp", *args.start)
            control("look", args.yaw, args.pitch)
            control("key", "f3", "tap")
            control("key", "f3", "down")
            control("key", "2", "tap")
            control("key", "f3", "up")
            control("bench", 5)
            control("render-distance", 64)
            control("bench", 20)
            warm = control("status")
            zero = warm["uptime_seconds"]
            result["status_samples"].append(metric_status(warm, zero, "end_of_rd64_warmup"))
            control("render-distance", 16)
            control("bench", 12)
            result["status_samples"].append(metric_status(control("status"), zero, "end_of_rd16_settle"))
            end = [args.start[0], args.start[1], args.start[2] - 256]
            for index in range(12 if args.variant == "sustained" else 4):
                if index == 4:
                    control("options-set", "maxFps", 260)
                    control("bench", 45)
                    result["status_samples"].append(metric_status(control("status"), zero, "end_of_extra_settle"))
                before = metric_status(control("status"), zero, "before_flight")
                a, b = (args.start, end) if index % 2 == 0 else (end, args.start)
                raw = control("fly", *a, *b, 8, args.pitch, "raw")
                after = metric_status(control("status"), zero, "after_flight")
                row = {"pass": index + 1, "direction": "out" if index % 2 == 0 else "back",
                       "phase": "late" if index >= 4 else "initial", "before": before, "after": after,
                       **{name: raw[name] for name in ("frame_ms", "cpu_ms", "gpu_ms")}}
                row["aggregate"] = aggregate([row])
                result["passes"].append(row)
                result["status_samples"].append(after)
                save()
                print(f"Pass {index + 1}: {row['aggregate']['average_fps']:.2f} FPS; "
                      f"P99 {row['aggregate']['p99_ms']:.2f} ms", flush=True)
            result["status_samples"].append(metric_status(control("status"), zero, "final"))
            result["aggregate_initial"] = aggregate(result["passes"][:4])
            if args.variant == "sustained":
                result["aggregate_late"] = aggregate(result["passes"][4:])
            result["complete"] = True
        finally:
            save()
            if proc is not None and proc.poll() is None:
                try:
                    control("quit", timeout=30)
                    proc.wait(timeout=35)
                except (RuntimeError, subprocess.TimeoutExpired):
                    # Only terminate the process started here; no installed game or unrelated PID.
                    proc.terminate()
                    proc.wait(timeout=10)
    print("Saved sanitized metrics. Copied world and private logs remain in --scratch-parent.")


if __name__ == "__main__":
    main()
