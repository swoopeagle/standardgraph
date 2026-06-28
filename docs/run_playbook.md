# StandardGraph Run Playbook

How to plan, approve, and execute pipeline runs — from quick daytime fixes
to multi-hour overnight jobs. Follows the batch execution pattern in CLAUDE.md.

---

## The two-phase ritual

### Phase 1 — Planning (5–10 min)

Before any multi-step run, produce a job table:

| # | Job | Device | Deps | Est. | Risk |
|---|---|---|---|---|---|
| 1 | fetch_portugal | Mini 3 → Studio | — | 30 min | low |
| 2 | embed + relate | Mini 2 + Mini 3 | 1 | 20 min | low |
| 3 | crosswalk | Mini 2 + Mini 3 | 2 | 15 min | low |
| 4 | rationale gen (high band) | Studio | 3 | 4 hr | low |
| 5 | mcp_test.py | MacBook | 3 | 10 min | low |
| 6 | build + publish v1.x | MacBook | 5 | 5 min | **token** |

Risk flags:
- `low` — reversible, affects only local DBs
- `token` — needs PyPI or HuggingFace credential; always prompted separately, never batched
- `destructive` — SQL DELETE/DROP against pipeline DB; confirm before running
- `irreversible` — PyPI publish, HuggingFace upload; cannot be undone

**Single approval**: present the table, wait for "go," then execute without per-step check-ins.
Report only: job completions, blockers, and final summary.

### Phase 2 — Execution

Run jobs in dependency order. Parallelize wherever deps allow
(Mini 2 + Mini 3 almost always run the same step simultaneously).
Token steps always pause and prompt separately, even mid-run.

---

## Job categories

### Ingestion — adding new curriculum systems

**When to use**: new country/state standard arrives, existing fetcher fails, URL goes stale.

**Steps**: fetch → embed → relate → crosswalk → eval → (if clean) ship

**Routing**:
- Fetcher with heavy PDFs (dense, multi-hundred-page) → Mac Studio (`gemma4:31b`)
- Fetcher with lighter PDFs (single subject, <100 pages) → IWPC (`gemma4:12b`) — saves Studio queue
  - `OLLAMA_BASE_URL=http://100.70.170.62:11434 OLLAMA_MODEL=gemma4:12b`
- Fetcher with structured data (web scrape, JSON) → mini only, no LLM needed
- Multiple fetchers → split across Studio + IWPC; both queue independently

**Watch for**:
- 0 standards extracted after 5+ chunks → PDF structure doesn't match parser; check the fetcher's page-range config
- Government PDF URLs go stale frequently; check with `curl -sI <url>` before running

### Embedding (`ingestion.shared.embed`)

**When to use**: after any new standards are ingested, or if embeddings are missing.

**Routing**: prefer IWPC (`http://100.70.170.62:11434`) when online — CUDA batch throughput is faster than Apple Silicon for embeddings. Falls back to local Ollama on each mini automatically via `post_ingest_pipeline.sh`. Never route to Mac Studio for embed.

**Parallelism**: both minis run embed simultaneously, both pointing at the same IWPC endpoint. IWPC serializes the requests; net result is still faster than two local M4/M4 Pro runs.

### Relate (`ingestion.shared.relate`)

**When to use**: after new standards added; rebuilds prerequisite/successor graph.

**Routing**: CPU-only, no Ollama. Run on both minis in parallel.

**Notes**: takes ~10 min for 158k standards. Output: `standard_relationships` table.

### Crosswalk (`crosswalk_engine.nlp_pass`)

**When to use**: after embed completes, or when new systems need hub mappings.

**Routing**: CPU-only cosine similarity on pre-computed vectors. Both minis in parallel.

**Notes**: ~15 min for full run. Output: `crosswalk_mappings` table (~96k rows).

### Rationale generation (`scripts/crosswalk_rationale_gen.py`)

**When to use**: after crosswalk to add LLM-written explanations to mappings.
This is the biggest single quality lift — turns `confidence: 0.73` into a
sentence explaining *why* two standards relate.

**Routing**: always Mac Studio, `qwen2.5:72b`. Do not use `gemma4:31b` for this —
the reasoning quality difference is significant for pedagogical context.

**Run order** (always process in this band sequence):
1. `--band high` (≥0.85) first — fastest, highest confidence, best ROI
2. `--band mid` (0.70–0.85) — catches the useful-but-uncertain zone
3. `--band low` (<0.70) — only if time allows; many of these will be flagged anyway

**System priority order** (most used → least used):
1. `ccss` ↔ AP math (calc-ab, calc-bc, stats, precalc)
2. `ngss` ↔ AP science (bio, chem, phys-1, phys-2, env)
3. `ccss` ↔ IB math (myp, dp)
4. US state math ↔ ccss
5. International (cambridge, sg-moe, etc.) ↔ ccss

**Throughput**: ~6 mappings/min with qwen2.5:72b → ~5,000 mappings per 14-hr overnight.

**Example**:
```bash
OLLAMA_BASE_URL=http://100.77.63.73:11434 \
OLLAMA_MODEL=qwen2.5:72b \
DB_PATH=~/projects/intl-math-standards-mcp/data/common_core.db \
uv run python scripts/crosswalk_rationale_gen.py \
  --band high --system ccss --sample 2000
```

### Crosswalk review / flagging

**When to use**: after rationale gen, to catch false-positive mappings.

qwen2.5:72b scores each mapping 1–5 and sets `flagged_for_review=1` for anything ≤ 2.
Flagged mappings are excluded from `map_standard` results.

**Run after rationale gen** (same model, queues automatically on Studio).

### Gap analysis

**When to use**: before writing new benchmark tests; identifies which standards have
no crosswalk path.

```bash
sqlite3 data/common_core.db "
  SELECT s.id, s.system, s.grade
  FROM standards s
  LEFT JOIN crosswalk_mappings m ON m.source_id = s.id
  WHERE s.system IN ('ap-calc-ab','ap-calc-bc','ap-stats','ap-precalc')
    AND m.id IS NULL
  ORDER BY s.system, s.grade;
"
```

AP standards with no CCSS mapping are candidates for:
- Two-hop paths (AP → some state → CCSS)
- Explicit `notes='no_ccss_equivalent'` annotation
- New dedicated benchmark tests that assert the fallback behavior is sensible

### Benchmark test expansion (`scripts/mcp_test.py`)

**When to use**: after any data quality run, to lock in known-good pairs.

Add pinned mapping pairs in the form:
```python
# CCSS → AP Calc AB: function definition → limits
r = map_standard("CCSS.MATH.8.F.A.1", to_system="ap-calc-ab")
check(mapping_confidence(r) >= 0.75, "CCSS fn definition → AP limits conf ≥ 0.75")
```

**Priority pairs to add** (US math/science focus):

| Source | Target | Min conf | Concept |
|---|---|---|---|
| `CCSS.MATH.8.F.A.1` | `AP.AP_CALC_AB.FUN-1.A` | 0.75 | Function definition |
| `CCSS.MATH.HSS.ID.B.6` | `AP.AP_STATS.DAT-1.E` | 0.80 | Scatter plots → regression |
| `CCSS.MATH.HSA.APR.B.3` | `AP.AP_CALC_AB.FUN-4.A` | 0.75 | Polynomial zeros → curve sketching |
| `NGSS.HS-LS1-6` | `AP.AP_BIO.ENE-1.A` | 0.75 | Photosynthesis/respiration |
| `NGSS.HS-PS1-7` | `AP.AP_CHEM.SPQ-2.A` | 0.75 | Equilibrium |
| `NGSS.HS-PS2-1` | `AP.AP_PHYS_1.INT-1.A` | 0.75 | Newton's laws |
| `IB_DP.MATH.AHL.5.19b` | `AP.AP_CALC_BC.LIM-3.D` | 0.80 | Series convergence |
| `IB_MYP.MATH.8.D3` | `AP.AP_PRECALC.1.1.A` | 0.70 | Functions and graphs |

### Grade-delta validation

**When to use**: periodically, after crosswalk runs.

Checks that `grade_delta` values in `crosswalk_mappings` are plausible.
A CCSS grade 3 standard mapping to an AP course with `grade_delta=0` is almost
certainly wrong.

Script: `scripts/eval/grade_delta_check.py` (to be written)

---

## Overnight run template

Use this when planning a full quality-improvement overnight:

```
Overnight run: [date] — [focus area]

Goals:
  - [what you want to be true by morning]

Jobs:
  Mac Studio (sequential, qwen2.5:72b):
    1. rationale gen: [systems], [band], [sample size]
    2. crosswalk review: [systems], [band]

  Mac mini 2 + Mini 3 (parallel):
    3. embed (if new data added)
    4. relate (if new data added)
    5. crosswalk re-run

  MacBook (in parallel with Studio):
    6. write new benchmark tests
    7. write gap analysis / grade-delta eval scripts
    8. commit all new scripts

  Morning:
    9. pull Mini 2 DB → MacBook
    10. mcp_test.py
    11. build + ship if clean
```

---

## Production readiness push template

Use when fixing issues and shipping a version:

```
1. Audit      — run mcp_test.py + eval suite, list all failures
2. Triage     — classify: data bug / code bug / test expectation wrong / missing content
3. Fix        — parallel where possible (data fixes on minis, code fixes on MacBook)
4. Verify     — re-run mcp_test.py, confirm zero regressions
5. Ship       — build → PyPI → HuggingFace → git tag
```

---

## Quick reference: when to use each model

| Task | Model | Device | Why |
|---|---|---|---|
| PDF → standards extraction (heavy) | `gemma4:31b-it-q8_0` | Mac Studio | Dense/long PDFs; best extraction quality |
| PDF → standards extraction (lighter) | `gemma4:12b` | IWPC | Saves Studio queue; good for single-subject PDFs |
| Rationale gen (high/mid band) | `qwen2.5:72b` | Mac Studio | Quality over speed; AP/IB accuracy matters |
| Rationale gen (low band / states) | `qwen2.5:14b` | IWPC | Parallel with Studio; acceptable quality for low-confidence mappings |
| Crosswalk review / scoring | `qwen2.5:72b` | Mac Studio | Same — quality over speed for human-facing notes |
| Embeddings | `nomic-embed-text` | IWPC (CUDA) | Fastest batch throughput; falls back to mini local if offline |
| Quick eval / classification | `qwen2.5:14b` | IWPC or Mini 2 | Fast, fits comfortably |
| Anything on Mini 3 | `qwen2.5:14b` max | Mini 3 | 16 GB hard ceiling; never exceed 10 GB model |
