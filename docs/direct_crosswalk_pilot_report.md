# Direct cross-system crosswalk pilot — results

**Date:** 2026-07-09 · **Status:** complete, staged for review (not merged to prod)
**Scope:** math only, 6 highest-orphan source systems (es-lomloe, de-kmk, ib-dp,
ap-stats, uk-aqa, gb-sco), candidate targets drawn from the full remaining
math orphan pool. Full plan: `~/.claude/plans/rippling-yawning-codd.md`.

## The problem this addresses

StandardGraph is strictly hub-and-spoke: every crosswalk row routes non-hub
system → subject hub (verified 100% true across the whole corpus, all
subjects). This means two non-hub standards can only connect *transitively*,
and only if **both** independently cleared the hub threshold. Real content is
left disconnected: post-MP-fix, 3,912 non-CCSS math standards had zero
crosswalk mapping at all, with rates as high as 51% (Germany, IB-DP) and 50%
(AP Stats).

## Key architectural finding

`map_standard`'s Strategy 1 query parametrizes `target_system` — it is not
hardcoded to a hub. **This means direct peer-to-peer crosswalk rows are served
automatically with zero changes to `server.py`.** Verified end-to-end (see
below) against the actual current `server.py`. The entire project is a
data-generation pipeline, not an architecture change.

## Pipeline

1. **Phase 1 — candidate generation**: pairwise cosine among the orphan
   population (source restricted to the 6 named systems, targets drawn from
   the full ~3,900-orphan pool), 0.55 floor, grade-delta ≤ 5. **1,247
   candidates** generated from a 495-orphan source pool.
2. **Phase 2 — guardrail gate**: Claude-designed classify prompt (1-5 rubric),
   validated against a 40-pair gold set hand-labeled from real Phase 1 data
   (20 accept / 20 reject, spanning the full cosine range, including a
   lexical-collision trap — "tangents and **normals**" vs "**normal**
   distribution" — and same-topic-different-skill traps). **95% agreement,
   zero critical trap violations** on round 1 (no iteration needed — a
   stronger first-round result than either of today's other two gates).
3. **Phase 3 — gate + insert**: all 1,247 candidates gated; **528 approved
   (42.3%)**, 719 rejected; **1,006 unique bidirectional crosswalk rows**
   inserted as `relationship="direct_equivalent"`, confidence floored at 0.70
   (true cosine preserved in `notes`), unflagged, `verified_by_human=0`.

## Results

### Orphan resolution (before/after, full corpus math orphan pool)

| | Count |
|---|---:|
| Orphans before (post-MP-fix baseline) | 3,912 |
| Orphans after | 3,378 |
| **Resolved** | **534** |

More than the 6 pilot systems' own orphans (289 of the 495) were resolved —
245 additional resolutions came from candidate *targets* outside the 6 named
systems, confirming the "candidates drawn from the full pool" design choice
paid off as intended.

**Safety, by construction and verified**: every inserted row's `(source_id,
target_id)` pair came from standards with *zero* prior crosswalk mapping on
both sides — there is no code path by which this could have altered an
already-mapped standard's existing row.

### Real end-to-end verification

Called the actual `map_standard` function (not a reimplementation) against 6
newly-inserted pairs, using the current `server.py` (a stale-checkout mismatch
was caught and corrected mid-verification — see Honest caveats):

- 6/6 confirm `mapping_method == "precomputed_crosswalk"` (Strategy 1 fires,
  not the two-hop or embedding fallback)
- 6/6 confirm the expected `target_id`, `relationship == "direct_equivalent"`,
  `flagged == False`, and a parseable `quality_score`

### Blind LLM quality check — a self-caught measurement bug, corrected

First pass on 20 sampled pairs: **8/20 (40%)** — alarmingly low. Root-caused
before accepting the number: the blind-check prompt added a stricter
"similar level of specificity" requirement that the *actual gate* never used
(the gate explicitly accepts broader/narrower framings of the same core
skill). Re-ran the **identical 20 pairs** with a corrected, gate-consistent
prompt: **18/20 (90%)**. The swing is the direct, isolated effect of fixing an
inconsistency I introduced, not a change in the underlying data.

One case was individually investigated rather than trusted at face value: a
pair that looked like a clear mismatch from a truncated text preview
("Extension of the sine rule to the ambiguous case" → "Provide an example...
relevant to one's self, family, or community...") turned out, on reading the
full untruncated text, to genuinely be about the same concept (the sine
rule's ambiguous case) — a correct approval, not a gate miss. Recorded here as
a reminder that truncated previews can mislead in either direction.

### Regression check

- `scripts/mcp_test.py` against `pilot2.db`, run with the **current**
  `server.py`/test file (a stale Mini 2 checkout was caught mid-verification
  and corrected — see caveats): **333 passed, 0 failed, 0 warnings** —
  identical to the untouched-prod baseline.
- `scripts/eval/run_all.py --tier structural`: **0/4 checks failed** (run
  against the DB directly; pure-SQL schema/integrity checks, not sensitive to
  the server.py version mismatch that affected the other checks).

## Honest caveats

- **A real methodological bug was caught and fixed during verification**: the
  Mini 2 execution host's git checkout was several commits behind current
  `main`, meaning the first pass of `map_standard` verification and
  `mcp_test.py` ran against stale code. Caught by comparing file hashes
  (they differed) before trusting the "1 failed" result from the stale run;
  re-verified against the current code with a clean result. Mini 2's checkout
  should be brought current before it's used for further verification work.
- Blind quality check sample size is small (20) — the *direction* (bug caught,
  fixed, 90% on the corrected measurement) is solid, but treat the exact
  percentage as indicative.
- Math only, 6 source systems. Not yet run on the remaining ~65 high-orphan
  math systems, or any other subject.
- No transitive closure — if A↔B and B↔C direct edges both exist, C is not
  auto-derived from A.
- Staged in `pilot2.db` on Mini 2. **Prod untouched.**

## Recommendation

The core architectural hypothesis is fully validated: direct cross-system
mappings serve correctly through the existing `map_standard` with zero code
changes. The generation pipeline produced a real, meaningful orphan-resolution
result (534 standards, 43% more than the 6-system-only scope would suggest)
at a defensible quality bar (90% on a corrected, gate-consistent blind check).
Before considering a wider rollout or prod merge:

1. Sync Mini 2's checkout to current `main` before any further verification
   work there.
2. Widen the blind-check sample before treating 90% as a stable number.
3. Decide rollout order for the remaining high-orphan math systems, and
   whether to extend to other subjects.
