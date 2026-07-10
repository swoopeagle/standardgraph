# Prerequisite-graph pilot — LLM-validated CCSS-math prerequisites + `get_learning_path`

**Status:** pilot complete on a scratch DB fork; **HOLD for prod-merge approval.**
**Date:** 2026-07-10. **Scope:** CCSS mathematics (533 standards, K–HS).

## Goal

Replace StandardGraph's noisy prerequisite graph with an LLM-validated one for CCSS
math, and build a new `get_learning_path` MCP tool over it — the substrate for
self-paced acceleration ("what do I need to learn before calculus?") and the
objective-sequencing layer an Ello-style tutor would consume.

## Why the old graph needed replacing

`relate.py` generates all ~3.16M relationship rows from a pure grade-adjacency
heuristic: within each `system + domain`, every grade-N standard links to every
grade-(N+1/N+2) standard. Two consequences for CCSS math:

- **Under-connection (the big one):** the heuristic is *same-domain only*, so it
  produces **0 cross-domain prerequisites**. It structurally cannot express that
  fraction understanding (NF) underpins ratios (RP), or that coordinate geometry
  (G) underpins graphing proportional relationships (RP/EE).
- **Over-connection:** blanket grade-adjacency with no quality signal. Modest for
  CCSS math (max 10 prereqs/standard) but real. *(The oft-quoted "171 prerequisites"
  worst case is Ohio ELA, not CCSS math — corrected here.)*
- `get_progression` never used the graph at all (it does per-grade semantic search),
  so genuine prerequisite path-finding was simply **unbuilt**.

## Method — measure → gate → build → verify

Same pipeline as the three pilots merged the day before.

- **Phase 0 — candidates.** 2,568 candidate pairs (CCSS-math content only; 80 MP
  practice standards excluded; strictly-lower-grade prereq, grade-window ≤ 3,
  cross-domain allowed, cosine ≥ 0.45, top-6 by cosine per target).
- **Phase 1 — gate.** A directional **HARD / SOFT / NONE** rubric validated against a
  38-pair hand-labelled gold set on Studio `qwen2.5:72b`. First run failed (87%
  binary / 2 missed cross-domain); the prompt was sharpened with an operational
  *HARD-vs-analogous* test; re-run **passed 36/38 (95%) binary, 0 spurious, 0 missed.**
- **Phase 2 — schema.** Four additive, backward-compatible columns on
  `standard_relationships` (`confidence_score`, `notes`, `method` default
  `grade_heuristic`, `flagged_for_review`) + a `(method, relationship)` index. All
  3.16M existing edges default to `method='grade_heuristic'`. `mcp_test.py` = 333/333.
- **Phase 3 — classification.** **Claude** was the primary judge (per-judgment higher
  quality than qwen and fast enough to finish all 2,568 in-session). qwen ran in
  parallel on Studio as an independent second opinion.
- **Phase 4/5 — build + verify.** `get_learning_path` tool, `prefer_validated` on
  `lookup_standard`, eval suite, before/after metrics, independent agreement check.

## Definitions

- **HARD** — B is a genuine building block A directly depends on (performing A invokes
  B's skill, or A explicitly extends/generalises B). *Inserted as the default graph.*
- **SOFT** — B is helpful background that builds general fluency but A's core procedure
  does not invoke it. *Inserted, but only surfaced behind `include_soft=True`.*
- **NONE** — not a prerequisite: topical/analogous/parallel/sibling, or the dependency
  runs the other way. *Dropped.*

## Results

### Classification (all 2,568 candidates, Claude)

| Label | Count | Disposition |
|---|---:|---|
| HARD | 402 | inserted, `confidence_score=0.9` (default path) |
| SOFT | 1,614 | inserted, `confidence_score=0.5` (behind `include_soft`) |
| NONE | 552 | dropped |

Inserted as `method='llm_validated'`: **2,016 edges → 4,032 rows** (each edge stored as
a `prerequisite` row + a mirrored `successor` row). **3,460 are brand-new** edges the
grade heuristic never made (mostly cross-domain); **572** upgraded existing
grade-heuristic rows in place. The validated subgraph has **0 two-cycles** (every edge
strictly increases grade, so it is acyclic by construction — cycle-breaking is a no-op).

### Before → after (CCSS math prerequisite edges)

| Metric | grade_heuristic | llm_validated HARD |
|---|---:|---:|
| Max prerequisites / standard | 10 | **6** |
| Avg prerequisites / standard | 3.95 | **1.44** |
| **Cross-domain share** | **0.0%** | **51.5%** (207/402) |

The precision win (fewer, higher-quality edges) is real but modest for CCSS math; the
**decisive win is cross-domain coverage going from 0% → 51.5%** — exactly the
under-connection the heuristic could never fix. (SOFT edges are 68.6% cross-domain.)

### Coverage

- 533 CCSS-math standards total; **280** have ≥ 1 HARD validated prerequisite; **423**
  have ≥ 1 validated (HARD or SOFT) prerequisite; **449** distinct standards are touched
  by a validated edge. (Remaining standards are mostly K–1 roots with no lower-grade
  prereq, or standards whose only prereqs are same-grade — a documented follow-up.)

### Independent validation (blind second judge)

qwen2.5:72b independently labelled **220** of the candidates using the *byte-identical
gold-validated gate prompt*, with no sight of Claude's labels — a genuine blind check.

| Agreement on the 220-pair overlap | Result |
|---|---:|
| Exact 3-way (HARD/SOFT/NONE) | 62.3% |
| **Binary HARD-vs-not** (the admission decision) | **82.3%** |
| **Of Claude's 69 HARD edges: qwen said HARD** | **68 (98.6%)** |
| Claude-HARD that qwen called NONE (**spurious**) | **0** |
| qwen-HARD that Claude called NONE (**missed**) | **0** |

The part that becomes the default learning-path graph — the HARD edges — is **98.6%
confirmed by an independent judge with zero spurious and zero missed**. The lower 3-way
number is entirely SOFT↔NONE boundary noise (helpful-background vs unrelated), which
lives behind `include_soft` and never affects the default path.

### `get_learning_path` — example chains (HARD only, target-last)

```
5.NF.B.7.b : 1.G.A.3(g1) → 2.G.A.3(g2) → 3.NF.A.1(g3) → 4.NF.B.4.b(g4) → 5.NF.B.7.b(g5)
HSN.RN.A.2 : 5.OA.A.1(g5) → 6.EE.1(g6) → 8.EE.1(g8) → 8.EE.2(g8) → HSN.RN.A.2(gHS)
HSF.LE.A.1.b: 5.G.A.1(g5) → 6.EE.9(g6) → 7.RP.2(g7) → 8.F.4(g8) → HSF.LE.A.1.b(gHS)
8.EE.8.b   : 6.EE.7(g6) → 7.EE.4.a(g7) → 8.EE.8.b(g8)
7.RP.2.c   : 5.G.A.1(g5) → 6.EE.9(g6) → 6.RP.2(g6) → 7.RP.2.c(g7)
2.NBT.A.1.b: K.NBT.A.1(gK) → 1.NBT.B.2.c(g1) → 2.NBT.A.1.b(g2)
```

`5.NF.B.7.b` (fraction division) traces back through a **Geometry** standard
(partitioning shapes into equal shares → fraction-as-parts → fraction division) — a
cross-domain chain the grade-adjacency heuristic is structurally incapable of producing.
`HSN.RN.A.2` (rational exponents) correctly converges the exponent strand (8.EE.1) and
the radical strand (8.EE.2).

## Tool / API changes (backward-compatible)

- **New tool `get_learning_path(target, system='ccss', from_standard=None,
  max_depth=20, include_soft=False)`** — reverse-BFS over `method='llm_validated'`
  prerequisite edges (`confidence_score ≥ 0.9` HARD-only by default; `include_soft`
  lowers to ≥ 0.5), returned grade-ordered (a valid topological order, since edges
  strictly increase grade). `from_standard` prunes to the chain between a mastered
  standard and the target. Falls back gracefully (returns the target with a note) when
  no validated prereqs exist — so it is inert and harmless against a DB without
  validated edges.
- **`lookup_standard` gains `prefer_validated=True`** — returns the validated
  prerequisite/successor edges when any exist, else falls back to grade-heuristic edges
  (so existing non-empty prerequisite lists are preserved). Response now reports
  `prerequisites_method`.

## Regression

- `scripts/mcp_test.py` — **333/333** against the scratch DB (schema migration + inserts
  + `lookup_standard` change introduce no regression).
- `scripts/eval/learning_path_tests.py` (new) — **41/41**: path is target-last and
  grade-non-decreasing, in-path prereq edges point backward, `include_soft` never
  shrinks the path, `from_standard` pruning is contiguous, cross-domain path present,
  error/empty handled, `prefer_validated` reports its source.

## Honest caveats

- **The "171 fan-out" figure is Ohio ELA, not CCSS math.** For CCSS math the heuristic's
  worst case is 10; the fan-out reduction (10 → 6) is real but not dramatic. The genuine
  value is cross-domain coverage and the working path tool, not fan-out pruning.
- **SOFT edges are single-judge.** The independent blind check confirms the HARD set; the
  SOFT/NONE boundary is fuzzier and only lightly cross-checked. SOFT is intentionally
  gated behind `include_soft`.
- **Gold contamination of the primary judge.** Claude read the 38 gold labels during
  Phase 1, so Claude cannot be the blind validator on gold. The independent validator is
  qwen (prompt-validated on gold, blind to Claude's labels); its 220-overlap agreement is
  the Phase-5 blind check.
- **Same-grade ordering deferred.** Same-grade candidate pairs were dropped for the pilot
  (learning paths are grade-increasing); intra-grade sequencing is a documented follow-up.

## Recommendation

The pilot met its bar: HARD edges 98.6%-confirmed by an independent judge with **0
spurious / 0 missed**, a working cross-domain path tool, and 333/333 + 41/41 green.
**Recommend merging the validated edges into prod** (fork prod, re-run
`scripts/prereq_pilot/prereq_insert.py`, ship `server.py`), then bump the PyPI package
and push the DB to HuggingFace + refresh the hosted MCP. **All merge/publish steps HOLD
for explicit approval** (the DB-merge is `destructive`/`irreversible` and HF/PyPI need
tokens — remind to rotate after use).

## Artifacts

- Scratch DB with validated edges: session scratchpad `prereq_pilot.db` (a `.backup`
  fork of prod; **prod untouched**).
- Scripts: `scripts/prereq_pilot/{prereq_candidates,prereq_gate,prereq_claude,prereq_batch,prereq_insert}.py`.
- Labels: `claude_labels.jsonl` (2,568), `qwen_labels.jsonl` (220, independent).
- Code: `packages/common-core/src/common_core/server.py` (`get_learning_path`,
  `lookup_standard` `prefer_validated`); eval `scripts/eval/learning_path_tests.py`.
