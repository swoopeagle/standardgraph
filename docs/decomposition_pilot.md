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

## Recommendation

**Proceed to a broader rollout, staged by sub-structure density**, not a flat
corpus-wide pass. Order: (1) CCSS HS, (2) AP/IB and other richly-lettered
frameworks, (3) the long tail. Each stage: promote sub-parts to first-class rows
additively, embed, regenerate affected crosswalks, measure the same way.

Open items to fold into the rollout:
- **Cluster-letter drift** normalization (grade 1 stores `1.G.A.1`, grade 6
  `6.EE.1`) — cheap, unblocks clean external joins.
- Decide crosswalk policy: keep parent-level mappings *and* sub-part mappings, or
  prefer sub-part when it wins. (Pilot kept both; A/B only compared.)
- Published `standards` count will grow — update stats/docs accordingly.

## Reproduce

Scripts in scratchpad: `promote_subparts.py`, `ab_analysis.py`, `llm_confirm.py`.
Scratch DB: `pilot.db` (copy of prod + 86 promoted rows + embeddings).
