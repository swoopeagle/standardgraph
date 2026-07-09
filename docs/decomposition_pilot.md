# Sub-standard decomposition pilot — CCSS-math K-8

**Date:** 2026-07-08 · **Status:** pilot complete, awaiting rollout decision
**Scope:** CCSS-math K-8 only, on a scratch copy of the DB (prod untouched).

## Hypothesis

Our `standards` rows store standards at *parent* grain — a standard that bundles
lettered sub-parts (`6.EE.2a/b/c`) is one row whose embedding is a **blurred
average** of several distinct ideas. Marble's os-taxonomy works at finer grain.
Claim: decomposing to sub-standard grain yields **sharper embeddings** and thus
**more precise crosswalk mappings** (higher confidence, correct sub-part
targeting, disambiguation of multiple source standards onto distinct sub-parts).

## What we did

1. Confirmed the Common Standards Project API still returns CCSS depth-3
   sub-standards (fail-fast gate — passed).
2. Promoted CCSS-math K-8 sub-parts from the inert `sub_standards` table to
   **first-class `standards` rows** (86 rows), additively — parents kept.
   K-8 CCSS went 230 → 316, closing the gap with Marble's ~310 K-8.
3. Embedded the 86 new rows (nomic-embed-text, local Ollama).
4. Controlled A/B using nlp_pass.py's exact cosine math: for three source
   systems (ga, tx, ca-ab), best CCSS target under **coarse** (parents only)
   vs **fine** (parents + sub-parts) candidate sets.
5. Blind LLM confirmation (qwen2.5:72b, randomized order) on the cases where a
   sub-part beat its parent.

## Results

| Source | src stds | fine mappings on a sub-part | coarse→sub-parted-parent cases | sub-part beats parent |
|---|---:|---:|---:|---:|
| ga    | 948  | 53 (8.1%)  | 115 | 15 (13.0%) |
| tx    | 844  | 70 (11.0%) | 76  | 12 (15.8%) |
| ca-ab | 1248 | 78 (7.5%)  | 124 | 5 (4.0%)   |

- **Precision:** 7.5–11% of fine mappings now target a *specific sub-part*
  instead of the umbrella parent.
- **Sharpening:** where a sub-part wins, mean cosine margin +0.03–0.06, up to
  **+0.22** (e.g. `GA.MATH.6.NR.4.2`: parent `6.RP.3` 0.745 → `6.RP.3.a` 0.963).
- **Disambiguation confirmed:** `GA.MATH.6.NR.3.5` and `6.NR.3.6` both mapped to
  the blurred parent `6.NS.7`; fine grain splits them to `6.NS.7.c` and `6.NS.7.d`.
- **Semantic validity:** blind LLM judge agreed the sub-part is the better target
  in **14/15 (93%)** of GA cases.

## Follow-up experiments (same day) that revised the conclusion

**CCSS HS extension — dud.** Promoting HS sub-parts added only 24 rows (HS math is
mostly single-statement; the letters in `HSA-APR.A.1` are cluster letters, not
sub-parts). A/B sub-part-beats-parent wins by target band: ga K-8=15 / HS=3,
tx K-8=12 / HS=0. **HS is not a rollout target.**

**Corpus bundling scan.** ~4,429 math standards corpus-wide carry bundling
signals (enumeration / semicolons / "including"). The density is on the SOURCE
side, not the CCSS hub: tx 371, nz-moe 354, ca-on 261, ca-qc 210, India 61% of
its standards; CCSS itself only 96.

**Source-side split validation (10 bundled TX standards, LLM-split + re-embed).**
8/10 resolved to MULTIPLE distinct CCSS targets when split (coverage the single
blurry mapping lost) — but only 2/10 improved top-1 confidence, and two failure
modes appeared: (a) process/practice standards (`TX.MATH.K.1.D`) fragment into
scattered ~0.70 noise, (b) the LLM over-splits ("create circles/triangles/
rectangles" → 3 redundant parts). Source decomposition is a **recall** gain, and
only for genuine multi-topic *content* standards.

## Honest read

- The effect is **real but localized at K-8 scale.** Only 29 of ~343 CCSS
  parents have sub-parts and there are just 86 sub-parts total, so the *mean*
  confidence gain across all mappings is tiny (+0.002–0.005). The win concentrates
  on the minority of mappings whose best target is a sub-parted standard — but
  there it is genuine and sometimes large.
- The payoff scales with sub-structure density. **HS CCSS** and many
  **international / AP / IB** standards carry far richer lettered sub-structure
  than K-8, so the addressable population corpus-wide is materially larger than
  this slice suggests.
- No downside observed: fine grain never *lost* a mapping (fine mapped ≥ coarse
  in all three systems); it only added precision.

## Recommendation (revised after follow-ups)

**Decomposition is a surgical accuracy tool, not a blanket operation.** A flat
corpus-wide pass would inject noise (process/practice standards, LLM over-split)
and hurt accuracy. Do TARGETED, guardrailed decomposition where the evidence
shows a win:

1. **Target-side (CCSS hub):** K-8 sub-part promotion is done in the pilot and is
   a genuine sharpening win. Skip HS. This slice is essentially complete.
2. **Source-side (states/international):** the larger opportunity, but gated. Only
   decompose multi-topic **content** standards; **exclude process/practice
   standards** (TEKS process, MP, generic "communicate/select tools" repeaters).
   Constrain the LLM split to distinct-topic boundaries and dedupe near-identical
   parts. Benefit is crosswalk **recall** (a bundled standard yields several
   targeted mappings instead of one blurry one).

**Crosswalk storage policy: hierarchical.** Store the precise winning edge at leaf
grain; materialize parent↔child containment so map_standard can roll up (preserves
cross-system transitivity) and so confidence isn't misrepresented. Do NOT store
redundant weak parent edges, and do NOT delete parent edges outright (breaks
transitivity + parent-level lookups). Type source→leaf `equivalent`, induced
source→parent `overlapping`.

Open items:
- **Cluster-letter drift** normalization (grade 1 `1.G.A.1` vs grade 6 `6.EE.1`).
- Build a **process/practice-standard classifier** (the guardrail) before any
  source-side pass.
- Published `standards` count will grow — update stats/docs accordingly.

## Reproduce

Scripts in scratchpad: `promote_subparts.py`, `ab_analysis.py`, `llm_confirm.py`.
Scratch DB: `pilot.db` (copy of prod + 86 promoted rows + embeddings).
