# StandardGraph — Project Status

*Last updated: 2026-06-15*

---

## What's been built

### Ingestion pipeline

Multi-stage pipeline (`packages/ingestion/`) that runs nightly via `scripts/overnight_run.sh`:

1. **Fetch** — pulls standards from source APIs and PDFs by subject:
   - US/Canada math & science from [commonstandardsproject.com](https://commonstandardsproject.com)
   - International math, AP, IB, Cambridge from official PDF syllabuses via Gemma 4 31B (Ollama)
   - US ELA, Social Studies, CS from state DOE PDFs via Gemma 4 31B
2. **Embed** — nomic-embed-text (768 dims) via Ollama; incremental (skips already-embedded standards)
3. **Relate** — builds prerequisite/successor relationships via keyword overlap
4. **Crosswalk (nlp_pass)** — cosine similarity maps each standard to its subject hub

Hub-and-spoke crosswalk architecture:

| Subject | Hub |
|---|---|
| Mathematics | CCSS Math |
| Science | NGSS |
| ELA | CCSS ELA |
| Social Studies | C3 Framework |
| Computer Science | CSTA K-12 (2017) |

`map_standard` supports three routing strategies in order: precomputed crosswalk → two-hop bridge (source→hub→target) → semantic embedding fallback.

### MCP server

FastMCP over stdio (`packages/common-core/src/common_core/server.py`). Six tools:

| Tool | Purpose |
|---|---|
| `search_standards` | Semantic search over all standards |
| `lookup_standard` | Fetch by ID with full text, prerequisites, successors |
| `get_progression` | Trace a concept across grade levels |
| `get_learning_path` | Ordered prerequisite study plan for a target standard |
| `map_standard` | Find closest equivalent in another curriculum |
| `list_systems` | Live system/standard counts |

Three MCP prompt templates: `/curriculum_assistant`, `/compare`, `/find_equivalent`.

### Eval suite

`scripts/eval/` — all deterministic except where noted:

| Script | Type | What it tests |
|---|---|---|
| `db_integrity.py` | Det | Empty texts, orphaned records, embedding completeness, confidence ranges, grade codes |
| `coverage.py` | Det | Known standard IDs, hub counts |
| `duplicates.py` | Det | Exact/near-duplicate detection |
| `crosswalk_quality.py` | Det | Confidence distribution, hub routing, collision |
| `search_quality.py` | Det | 15 golden queries, Recall@5 ≥ 70% |
| `search_filter_tests.py` | Det | Grade/domain/system filters, 10 cases |
| `coverage_matrix.py` | Det | All 256 systems semantically reachable (cosine ≥ 0.45) |
| `lookup_standard_tests.py` | Det + LLM | 10 cases: expansion, sub-standards, international IDs, grade validity |
| `two_hop_bridge_tests.py` | Det + LLM | 8 international-to-international pairs via hub |
| `subject_crosswalk_tests.py` | Det + LLM | 11 ELA + SS crosswalk pairs across confidence tiers |
| `map_fallback_tests.py` | Det + LLM | 5 pairs with no precomputed or two-hop path |
| `persona_tests.py` | LLM | 5 personas × 4 scenarios, tool quality |
| `crosswalk_semantic_tests.py` | LLM | 13 pairs across 4 confidence tiers (math focus) |
| `adversarial_tests.py` | LLM | 10 edge cases, graceful degradation |
| `progression_coherence_tests.py` | LLM | 8 grade progressions, pedagogical coherence |
| `e2e_claude_test.py` | Claude API | 12 scenarios via live MCP + Anthropic API (requires key) |

Run all deterministic checks: `uv run python scripts/eval/run_all.py`

LLM checks use Gemma 4 26B locally: add `--local-judge` to any script.

---

## Current coverage (2026-06-15)

| Subject | Systems | Standards |
|---|---|---|
| ELA | 52 | 46,062 |
| Social Studies | 51 | 42,740 |
| Science | 59 | 33,964 |
| Mathematics | 82 | 22,543 |
| Computer Science | 12 | 1,198 |
| **Total** | **256** | **146,507** |

Embeddings: 126,939 / 146,507 (87%) — embed job in progress as of this writing.
Crosswalk mappings: 18,048.

---

## Eval results

### `run_all.py` (deterministic, 2026-06-15)

| Check | Status | Notes |
|---|---|---|
| DB integrity | FAIL | 69 standards with text <5 chars (PDF extraction artifacts) |
| Coverage & known IDs | OK | |
| Duplicate detection | OK | 0 exact/near-dupes |
| Crosswalk quality | OK | |
| Search quality (golden) | OK | Recall@5 ≥ 70% |
| Search filter accuracy | OK | 10/10 filter tests |
| Coverage matrix (256 systems) | OK* | *passes once embed job completes |
| lookup_standard correctness | OK | 10/10 det pass |

### LLM eval results (Gemma 4 26B, 2026-06-15)

| Script | YES | PARTIAL | NO | Notes |
|---|---|---|---|---|
| persona_tests.py | 14 | 5 | 1 | NO: TX→CCSS multiply-by-10 → rounding (conf=0.749, wrong skill) |
| crosswalk_semantic_tests.py | 9 | 4 | 0 | MEDIUM tier (0.81–0.84): 33% YES rate |
| adversarial_tests.py | 8 | 0 | 1 | NO: quantum entanglement in CSTA (false positive, expected) |
| progression_coherence_tests.py | 7 | 1 | 0 | PARTIAL: NGSS evolution K–HS (middle grades less scaffolded) |
| lookup_standard_tests.py | 5 | 0 | 0 | |
| two_hop_bridge_tests.py | 3 | 5 | 0 | PARTIALs are informative scope differences, not wrong |
| subject_crosswalk_tests.py | 6 | 4 | 1 | NO: ny-ela→ccss-ela MEDIUM tier (syntax vs close reading) |
| map_fallback_tests.py | 0 | 4 | 1 | NO: gh-nacca→au-acara (rational numbers vs factors — false positive) |

---

## Known quality issues

**69 standards with critically short text (<5 chars)** — PDF extraction artifacts where sub-item labels ("Copy", "Rome", "Fire") got stored as the full standard text. Affects 11 systems (Cambridge, ZA_CAPS, and several US SS state systems). Fix: improve PDF extraction or manually curate.

**MEDIUM-tier crosswalk accuracy (~33% YES at conf 0.81–0.84)** — NLP cosine similarity at this tier finds related but not always equivalent concepts. The system prompt instructs Claude to flag these as "worth verifying." For data-quality use: only trust mappings ≥ 0.85.

**ELA crosswalks have more false positives at the same confidence thresholds vs math** — ELA standards share generic academic language ("analyze," "evaluate," "text evidence") that inflates cosine similarity without semantic equivalence. MEDIUM-tier ELA mappings should be treated with extra skepticism.

**Embedding fallback (map_standard strategy 3) returns 0 YES in eval** — finds the right conceptual neighborhood but misses precise grade-level and scope alignment. One genuine false positive: gh-nacca rational numbers → au-acara factors/multiples (surface "number relationships" similarity). Use fallback results as starting points only.

**Dense-embedding false positives (inherent)** — "quantum entanglement" scores ~0.52 against CSTA networking standards. Not a data bug; inherent to dense retrieval. The adversarial eval confirms Claude (as MCP host) handles this correctly by not surfacing these as valid results.

**Grade-level mismatches in ELA crosswalks** — CA ELA standards sometimes map to CCSS-ELA with ±1 grade offset. CA adopted CCSS with modifications that shifted some standards by a grade. Expected but worth flagging.

---

## Outstanding work

- **DB integrity fix** — 69 short-text standards need to be re-extracted or removed
- **Full Gemma eval suite** — run all `--local-judge` scripts together after DB is clean
- **e2e_claude_test.py** — requires `ANTHROPIC_API_KEY`; costs ~$0.25–0.50 for 12 scenarios
- **International ELA/SS** — subject expansion planned (see `docs/subject_expansion_plan.md` in memory)
- **CS coverage** — currently 11 states; expanding

---

## Infrastructure

- **Languages/tools:** Python 3.11, uv workspace monorepo
- **DB:** SQLite (`data/common_core.db`) — standards, embeddings (BLOBs), relationships, crosswalk mappings
- **Embedding model:** nomic-embed-text via Ollama (Mac Mini at localhost:11434)
- **LLM extraction/eval:** Gemma 4 31B (Mac Studio at 169.254.1.1:11434), Gemma 4 26B (Mac Mini)
- **Overnight pipeline:** `scripts/overnight_run.sh` via launchd
