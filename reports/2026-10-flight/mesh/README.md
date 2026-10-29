# Mesh scratch evidence

Companion evidence for issue #4041 and `codex/mesh-buffer-reuse`, based on `origin/main` at `bd665f28a`.
The chart compares the current branch's fresh padding wrapper with its retained padding buffers.
It is not a prepatch-versus-PR A/B benchmark, whole-mesher benchmark, allocator-call trace or FPS measurement.

## Reproduce

From the repository root, with Rust and the platform build dependencies available:

```sh
cargo test --profile fast -p horizon-client-render --lib benchmark_padded_reuse -- --ignored --nocapture --test-threads=1
```

Save the printed JSON records, or use the supplied `scratch-observations.jsonl`. The records contain no paths or game data.
To render the chart, install Python 3 and matplotlib, then run:

```sh
python render_scratch_evidence.py scratch-observations.jsonl
```

The script produces PNG/SVG charts, a CSV of all observations, and a JSON summary. It rejects incomplete observations.
It has no workspace-specific import paths. The default output directory is the script's directory; `--out` selects another.

## Protocol

- One synthetic chunk contains 4,096 block IDs, cycling from 1 through 7. It is read with missing neighbor chunks; no model assets are needed.
- Both paths are warmed for 1,024 fills before timing.
- Nine samples per path each time 4,096 identical padding fills. Fresh/retained execution order alternates between paired samples.
- Rust `Instant` measures wall-clock elapsed time in a single test thread. The test checks that retained block, light and unpack-buffer addresses stay unchanged.
- The fixed retained buffer capacities total 56,384 bytes in this run. The visibility stack and CPU geometry pool are outside this microbenchmark.
- Local run: Windows x86-64/MSVC, Rust 1.99.1, optimized `fast` profile, Intel Core i9-13900K. Core affinity, CPU frequency and background load were not controlled.

| Current padding path | Median µs/fill | Minimum | Maximum |
| --- | ---: | ---: | ---: |
| Fresh | 11.181 | 10.962 | 13.852 |
| Retained | 10.505 | 10.203 | 10.953 |

The retained median was 6.0% lower in this run. Every sample is included. No statistical significance is claimed.
The fresh wrapper allocates/initializes storage before `fill` clears it; it is not identical to the prepatch initializer.
These observations cannot establish a whole-PR or frame-time improvement. The historical flight/FPS results came from a bundled build with other changes and are separate evidence.

## Correctness and resource gate

The normal crate tests cover direct chunk-read equivalence, independent visibility reference fixtures, geometry-state reset,
retained capacity, count limits, cumulative byte limits, oversized rejection, and pool accounting.
The explicit full-geometry test needs the player's prepared Minecraft 26.3 resources. Point
`HORIZON_MESH_TEST_RESOURCES` at that directory, or prepare `.local/horizon-client/26.3`, then run:

```sh
cargo test --profile fast -p horizon-client-render --lib reused_mesh_matches_fresh_geometry -- --ignored --nocapture --test-threads=1
```

The resource-backed test passed locally. It compares complete vertex bytes, block entities, visibility and side buckets
through empty/dense/sparse sections, changed neighbors, graphics options and resource reload. It also checks lazy allocation
on the first uniform-air section. Explicit invocation fails if resources are missing, rather than silently skipping.
Never commit prepared resources or game assets.

The required self-check was run with `python tools/pr_ready.py --base origin/main --quick`; its complete result is in
`SELF_CHECK.md`. Public-tree, rustfmt, clippy, all 562 default-profile render tests and doc tests passed. One Python failure
also occurs on unmodified main; parity harnesses remain for CI. The additional optimized full-render run reported one failure
in an untouched graphics validation test; its baseline reproduction is tracked separately from this microbenchmark.
