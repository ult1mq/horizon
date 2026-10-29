# Follow-up to PR #3961: enforce the outstanding mesh-section budget

This is a narrow follow-up patch for [PR #3961](https://github.com/horizon-rust/horizon/pull/3961), based exactly on commit [`89b737d88aeb315ea6cb20d96d09332e2551d814`](https://github.com/horizon-rust/horizon/commit/89b737d88aeb315ea6cb20d96d09332e2551d814). It complements that PR's nearest-first bounded scheduling. It is prepared for review with the existing work; no separate main-branch PR has been opened for this dependent patch.

[streaming-limits.patch](streaming-limits.patch) changes only `crates/horizon-client-render/src/streaming.rs`: 87 insertions and 3 deletions, including two regression tests. It extracts the outstanding-job counter and strict section budgeting from the earlier combined local build. Mesh scratch reuse, mesh pooling, allocator changes, LOD retirement, and unrelated source changes are excluded. No additional dependency is introduced.

## Why the existing budget can be exceeded

There are two distinct counting problems in the base commit:

1. **A map of current section sequences is not a count of submitted jobs.** `meshing` maps a section key to its newest submitted sequence. Submitting another sequence for that section replaces the entry while the previous worker snapshot still exists. Resource reload clears the map; server forget and distance-based unload remove keys. None of those operations cancels the queued/running mesh job. The old result will arrive later and be discarded as stale. Consequently, `workers * 32 - meshing.len()` can grant new capacity while obsolete work still owns snapshots or completed results. For example, 32 submitted sequences for one section occupy one map entry, and clearing that entry makes the map empty before any of those 32 results arrives.

2. **Candidate entries count columns, but each submission counts a section.** The base code passes the remaining section budget to `nearest_first(&mut candidates, room)`, then submits every dirty section of each selected column. With room for one job, selecting one column containing multiple dirty sections already overshoots. With a large initial budget, selecting that many columns can multiply the intended bound by the number of dirty sections per column. The loop does not decrement its budget while submitting sections.

## Changes and invariant

`MeshJobs` counts every submitted `Job::Mesh`, including superseded or unloaded work, until its `Done::Meshed` result is consumed by `update`. The counter increases immediately before submission. It decreases at the start of the result branch, before sequence or loaded-column checks, so valid, stale, and unloaded results all release exactly one slot. Reloading resources or forgetting keys does not reset it. Results received while saving/waiting stay counted in `deferred` until `update` consumes them.

Scheduling computes a mutable remaining budget from that counter. It visits the selected nearest columns in the existing order, submits only as many section bits as fit, decrements the budget by the actual selected section count, and stops at zero. Unsubmitted section bits remain dirty, allowing the next update to finish a partially submitted column rather than losing work. The existing nearest-first selection, per-column section order, worker multiplier, result validation, and upload behavior remain in place.

For a fixed worker count, the intended mesh-stage invariant is:

```text
submitted mesh jobs - consumed mesh results <= workers * 32
```

The counter covers queued, executing, and completed-but-unconsumed mesh jobs. It is a job-count bound, not a byte bound on geometry or a limit on every streaming stage. Lighting's separate map-based budget is outside this patch. The existing `busy()`/`stages()` diagnostics continue to use current-key counts; they are not exposed as measurements of the new outstanding-job counter.

## Regression coverage and validation

The patch includes two tests already present in the combined local implementation:

- `stale_and_unloaded_mesh_jobs_keep_capacity_until_the_result_arrives`: 32 successive sequences for one section leave one latest-key entry; clearing it does not free capacity; consuming each result frees one slot.
- `mesh_submission_bounds_sections_and_keeps_the_remainder_dirty`: a budget covering one whole column and one additional section stops at that limit, retains the other section bits, and permits them to be submitted on a later update.

For this extracted patch, `git apply --check` succeeded against the exact base file, application matched the expected modified source after line-ending normalization, reverse application checked cleanly, and `rustfmt --edition 2024 --check` passed. No Cargo build, unit-test execution, or new game run was performed for this extraction. Earlier results for the combined build do not substitute for testing this exact follow-up in the target branch.

Suggested checks after applying it in the PR author's complete checkout:

```console
git apply --check streaming-limits.patch
git apply streaming-limits.patch
cargo test -p horizon-client-render stale_and_unloaded_mesh_jobs_keep_capacity_until_the_result_arrives
cargo test -p horizon-client-render mesh_submission_bounds_sections_and_keeps_the_remainder_dirty
```

Review the single mesh submission site and every `Done::Meshed` consumption path together. A future cancellation path that drops a queued job without returning a result would need to release a slot explicitly. If worker counts become mutable, specify how a lowered limit drains existing work rather than assuming the invariant instantly holds at the new limit. Current construction fixes the thread count for the lifetime of `Streaming`.

## Performance evidence and integration

No isolated FPS or frame-time benefit is claimed for this patch. The earlier flight measurements used the combined changes, a different build profile, and an older source baseline. Their frame-time and LOD-residency charts cannot identify this follow-up's contribution.

A focused follow-up measurement would instrument submitted-minus-consumed mesh jobs during repeated section invalidations, resource reloads, and unload/reload cycles. Confirm the bound and eventual dirty-section completion first, then measure queue memory and frame times in repeated controlled runs. Because a stricter bound can change chunk completion latency, record near-player completion as well as peak outstanding jobs. Coordinate integration with PR #3961's author and rebase the patch if that PR changes its scheduling or result paths.
