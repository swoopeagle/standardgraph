# Crosswalk Quality Audit — 2026-07-12

_Independent 120-mapping stratified audit (Fable agent, read-only). Every headline
claim below was re-verified against `~/.standardgraph/common_core.db` by the main session._

## Verified DB-wide facts

| Claim | Verified value |
|---|---|
| grade_delta outliers `ABS(grade_delta)>12` | **1,724 rows** (exact) |
| Distinct `relationship` values | **only `equivalent`** (all 105,156) |
| Unscored nlp_pass band, cosine 0.70–0.85 | **26,327 rows** |
| Retrieval miss id 2380383 | `nv-ela …W.9-10.9` → `ccss-ela …W.8.9` while verbatim `ccss-ela.CCSS.ELA-Literacy.W.9-10.9` **exists** |
| Cross-subject bleed | `IA.SCI.W.9-10.9` = an ELA writing standard living in the science table |

## Headline

The real risk pool is **not** high-confidence-unscored rows (those are CCSS-clone state
standards, near-verbatim, mean quality ~4.8 — safe). It's the **26,327 unscored rows at
cosine 0.70–0.85**: in a 40-row sample of that band, **43% scored ≤2**. Extrapolated,
roughly **9–11k mappings served as "equivalent" are weak-to-wrong**, with no quality signal
distinguishing them from scored rows in the API.

## Failure patterns (share of 120-row sample)

1. **Grade-band mismatch labeled "equivalent" — ~33%.** All rows are `relationship='equivalent'`
   even at |grade_delta| up to 9. (e.g. HS "rationing" → K-2 "costs of production".)
2. **Lexical/cosine trap — ~17%.** Shared vocabulary, different concept. (Namibia g3
   multiplication-by-decomposition → CCSS K teen-number compose/decompose; the word
   "decomposition" carried the cosine.)
3. **Retrieval near-miss where an exact target exists — ~2.5%** but most embarrassing
   (id 2380383). Weak sibling rows also dilute the **6,016 sources carrying 2–3 mappings**.
4. **Generic-practice ↔ specific-content bleed — ~4%** (generic SEP → specific NGSS content).
5. **Cross-subject bleed (ingestion-side) — ~2%** (ELA writing standard inside the science/SS table).
6. **Source-text artifacts — ~4%** (truncated stems, glossary entries ingested as standards).
7. **grade_delta parse bug — 1,724 rows.** Source `grade='9'` parsed as 99 → grade_delta −90…−99.
8. **CSTA hub gap:** no Level 3B standards in the hub, so state 3B standards force-map onto 3A.

## Scorer calibration

60 stored-vs-independent pairs: agreement 57%, stored higher 37%, stored lower 7%; mean bias
**+0.32 (modestly generous)**. Reliable at the extremes (every stored 5 was genuine); inflation
concentrated in the **stored-3 band** — many 3s pair thin overlap with 3–9 grade gaps and should
be 2s. Treat stored-3 as "weak, use with caution," or re-score the 3-band penalizing
|grade_delta| ≥ 3.

## Recommended actions (priority order)

1. **Score or threshold-prune the 26,327-row unscored 0.70–0.85 band** (~9–11k weak). The
   ≥0.85 unscored band is safe as-is. _Note per [[feedback_nlp_pass_overwrites_scores]]: snapshot
   notes before any regeneration._
2. **Fix the grade-'9'→99 parse** in grade_delta (1,724 rows) — normalization + regenerate.
3. **Exact-text pre-pass** so verbatim targets always win; dedupe weak sibling rows among the
   6,016 multi-mapped sources.
4. **Ingestion filters:** drop truncated stems, glossary entries, and literacy standards embedded
   in science/SS documents.
5. **Ingest CSTA Level 3B** to unblock correct HS CS mappings.

Sample script + raw sample (seed 42, reproducible):
`scratchpad/sample_audit.py`, `scratchpad/sample.json`.
