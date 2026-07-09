# CCSS Mathematical Practice standards — missing-data fix

**Date:** 2026-07-09 · **Status:** complete, staged for review (not merged to prod)

## The finding

While investigating why cross-system standards were "orphaned" (no crosswalk
mapping to anything), a sample of orphan-to-orphan cosine matches revealed a
pattern: the highest-scoring cross-system pairs were consistently **practice/
competency standards** ("use appropriate tools for problem-solving,"
"communicate mathematical ideas") — content that exists in many frameworks
(Germany's process competencies, Spain's competency framework, Scotland's
"I have worked with others...") but had nothing to map to. Root cause: **CCSS's
own 8 Standards for Mathematical Practice (MP1-MP8) were never ingested into
our database at all** — not filtered, not embedded, just absent. This is a
data-completeness gap in the original CCSS ingestion, not a crosswalk-tuning
issue.

## What was done

1. Pulled verbatim MP1-MP8 text directly from the current corestandards.org
   PDF (domain migrated from corestandards.org to thecorestandards.org since
   original ingestion; text itself unchanged since 2010).
2. Inserted as first-class CCSS standards: **80 rows** (8 practices x 10
   grades K-HS). One row per grade, not one grade-neutral row, because our
   crosswalk engine filters on `grade_delta` (rejects `abs(delta) > 5`) — a
   single HS-tagged row would incorrectly reject a kindergarten source match.
   This also mirrors how CCSS materials are commonly cited in practice
   ("3.MP.1", etc.).
3. Embedded all 80 rows (nomic-embed-text).
4. Regenerated the hub crosswalk for every non-CCSS math system (not just the
   11 from the source-decomposition run) against the now-larger hub, since the
   orphan population spans the whole corpus.

## Results (measured against a pre-fix snapshot, isolated from the separate
source-decomposition work)

| | Count | % |
|---|---:|---:|
| Original orphans (parent standards, pre-fix) | 4,305 | — |
| Now mapped | 393 | 9.1% |
| — resolved to an MP standard (validates the mechanism) | 212 | — |
| — resolved to regular content (side effect of full recompute) | 181 | — |

**Safety check — the real risk was generic MP language "stealing" an existing
good content match.** Of 22,848 previously-mapped standards, 660 (2.9%) had
their target change after the full recompute — but **zero** changed to an MP
standard. The failure mode did not occur.

## Honest caveats

- 9.1% orphan resolution is real but modest relative to the total orphan
  population (4,305) — this fix targets specifically the practice/competency
  slice (~11% of orphans by the earlier keyword estimate), not the much larger
  genuine content-coverage gap.
- The 660 non-MP target changes weren't individually spot-checked; the
  critical safety property (no MP displacement) was verified directly, but a
  wider review of that churn would be reasonable before a prod merge.
- Staged in `pilot2.db` on Mini 2. Prod untouched.

## Recommendation

Low-risk, positive-evidence fix — safe to fold into the same prod-merge
decision as the source-decomposition work. The much larger remaining gap
(~3,900 standards, genuine content CCSS doesn't cover) is a separate,
architecturally bigger question — see the direct cross-system mapping
planning doc.
