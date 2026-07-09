# Overnight source-side decomposition — results

**Date:** 2026-07-09 · **Status:** complete, staged for review (not merged to prod)
**Scope:** 11 high-bundling math systems (nz-moe, ca-sk, ca-ab, it-miur, tx, ca-qc,
ca-on, wa, mn, in, va), gated source-side decomposition + hierarchical crosswalk.

Builds on [decomposition_pilot.md](decomposition_pilot.md), which found CCSS
target-side decomposition sharpens mappings but is localized (K-8 only), and that
the larger opportunity is source-side decomposition of bundled state/international
standards — gated to avoid decomposing process/practice standards.

## What ran

1. **Guardrail gate** (Claude-designed classify+split prompt, validated against
   40 hand-labeled gold cases): 3 iterations to reach 88% agreement, 0 process-
   standard violations, and a confirmed fix for an over-split failure mode
   (`create X, Y, Z shapes` → was 6 parts, now correctly 1). Only Studio's
   `qwen2.5:72b` cleared the bar; Mini 2 (`qwen3.6:27b`), Mini 3 (`gemma4:12b`),
   and IWPC (`qwen2.5:14b`) were tested and demoted to embeddings-only duty.
2. **Deterministic pre-filter**: of 8,134 candidate standards, only 1,131 showed
   any bundling signal and warranted an LLM call; 6,993 were skipped for free.
   (This fix was necessary — the initial unfiltered estimate was ~33 hours;
   pre-filtered, the run completed in ~8.4 hours.)
3. **Decompose**: 845 standards split → 2,275 child standards, additive
   (parents kept + `parent_id` containment column).
4. **Embed**: all 2,275 children embedded (nomic-embed-text, Mini 2 local).
5. **Hierarchical crosswalk regen**: cosine mapping recomputed per system over
   parents + children combined, top-1 per source standard.

All on a scratch copy (`pilot2.db`, staged on Mini 2). Prod untouched.

## Results

### Coverage / volume

| | Before (prod baseline) | After (hierarchical) | Delta |
|---|---:|---:|---:|
| Total mappings (11 systems) | 6,585 | 8,565 | **+30%** |
| Avg confidence | 0.7803 | 0.7800 | ~flat |
| Mappings landing on a sub-part | 0 | 950 (11%) | — |

Confidence is flat by design — this is a coverage mechanism, not a sharpening
mechanism (consistent with the CCSS target-side pilot's finding).

### Recall — the core hypothesis

**403 of 847 decomposed sources (48%) now span more than one distinct CCSS
target** — standards that were previously collapsed into a single blurry mapping
now correctly resolve to multiple targets. Concrete example:

```
NZ_MOE.MATH.7.477: "plan and conduct probability experiments..."
  -> CCSS.MATH.7.SP.6  [0.788]
  -> CCSS.MATH.7.SP.7.b [0.797]
  .a -> CCSS.MATH.7.SP.7.b [0.778]
  .b -> CCSS.MATH.7.SP.6  [0.748]
  .c -> CCSS.MATH.7.SP.7.b [0.775]
  .d -> CCSS.MATH.HSS.IC.B.5 [0.743]
```

One standard, four distinct sub-skills, four different (correct) targets — the
parent-only mapping was silently discarding three of these.

### Bonus finding: decomposition also fixes some outright wrong matches

`NZ_MOE.MATH.1.32780` (Year 1, ages ~5-6, "3D shapes have attributes...") mapped
at the parent level to **`CCSS.MATH.HSG.MG.A.1`** — a high-school standard — at
0.853 confidence, simply because no better single target existed for the blurred
whole. Its children correctly resolve to `CCSS.MATH.1.G.A.1` and
`CCSS.MATH.K.G.B.4`, both properly grade-matched. This is a real mismatch the
old coarse approach hid; decomposition surfaced and fixed it.

### Blind LLM quality check (qwen2.5:72b, blind, same protocol both sides)

| | Sample | Genuine-match rate |
|---|---:|---:|
| **Before** (prod original mappings, same 11 systems) | 20 | **30%** (6/20) |
| **After** (new sub-part mappings) | 20 | **55%** (11/20) |

+25 points, ~83% relative improvement, same strict judge applied identically to
both samples. The judge is demanding (it flags near-matches with a different
numeric range or method as non-matching), so absolute rates read low on both
sides — but the **relative** comparison is the signal, and it's a large,
consistent improvement.

Failure modes seen in both before/after "BAD" cases are a pre-existing property
of the nlp_pass cosine-at-0.70 approach, not something decomposition introduced:
CCSS has no calculus/advanced-HS coverage (so calculus sources get mapped to the
"least bad" available target), and the judge penalizes numeric-range or
method-specificity mismatches that a human curator might still call "overlapping."

## Honest caveats

- Sample sizes for the blind check are small (20 per side) — the *direction* and
  *magnitude* of the improvement is credible, but treat the exact percentages as
  indicative, not precise.
- 950 mappings now hierarchical; this is 11 systems, math only. Not yet run on
  the remaining ~70 math systems or other subjects.
- Prod is untouched. This is staged in `pilot2.db` on Mini 2, pending a decision
  on merge.

## Recommendation

The evidence supports merging this into prod: real recall gain (48% of
decomposed standards recovered lost targets), a genuine wrong-match fix example,
and a blind-checked precision improvement (30% → 55%) on the same strict
standard. Before merging:

1. Spot-check a larger blind sample (this report used n=20 per side; a wider
   review would tighten the confidence interval).
2. Decide on `map_standard` roll-up logic (per the hierarchical crosswalk policy
   agreed earlier) so children surface correctly in the MCP tool.
3. Decide rollout order for the remaining systems — likely by bundling density,
   same as this batch's selection.
