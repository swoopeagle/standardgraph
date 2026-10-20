# CONTEXT - StandardGraph

## 2026-10-19 - crosswalk-quality pass (branch `crosswalk-quality`, worktree ../standardgraph-quality)

**Result: a cosine floor of 0.75 beats baseline on held-out gold, at a real coverage cost. Applied to the copy `~/.standardgraph/common_core_quality.db` only (live DB untouched; `apply_cosine_floor.py` refuses to write `common_core.db`).**

- **What the "LLM score" is:** `[LLM score N/5]` in `crosswalk_mappings.notes` (1-5), written by `scripts/crosswalk_rationale_gen.py` / `score_batch.py`. The scorer prompt *included the cosine and grade delta* (anchored). Score <=2 sets `flagged_for_review=1`; the server hides flagged edges by default (`include_flagged`). **But the flag is not applied consistently:** 28,081 edges scored 1-2 are still unflagged (405 are score 1). Exact-match rows are `[exact-match 5/5]`. All 208k edges are `method=nlp_pass` top-1 hub cosine >=0.70 (no other methods).
- **Gold v2** (`data/crosswalk_gold_v2.csv`, rubric `docs/crosswalk-gold-rubric.md`, sampler `scripts/gold_v2_sample.py`, merge `scripts/gold_v2_build.py`): 209 pairs = original 65 + 128 new unflagged (stratified subject x US-state/intl/AP x LLM score) + 16 flagged. Labelled BLIND (text/grade/system only) by 2 independent sonnet agents, 13 disagreements adjudicated by a 3rd. **Kappa 0.90 (3-class), 0.95 (strict Y vs not), 0.90 (lenient N vs not); 94% raw agreement.** Caveat: both labelers are the same model family on one rubric, so kappa overstates independence and "gold" means "Claude-with-rubric", not a human teacher. Ian spot-checking ~30 pairs would be the real validation.
- **The earlier non-blind labels were inflated.** Same 65 pairs: strict 24/65 (37%) -> 10/65 (15%) blind; lenient 47/65 (72%) -> 44/65 (68%). 14 of 24 old "Y" became "P"; agreement old-vs-blind 44/65, kappa 0.52. Mostly a stricter exact/partial line, not more wrong links.
- **Baseline served graph (unflagged, population-reweighted from the stratified sample): strict 33%, lenient 79%** (raw unweighted sample 18% / 60% because it over-samples low-score cells). Flagged edges: 0/16 strict, 5/16 lenient, so the existing flag is right. LLM score 1: 0/22 lenient; score 2: 39% lenient 0% strict; 3: 65%/9%; 4: 90%/30%; 5: 93%/66%.
- **Where wrong links come from:** (1) low cosine: <0.75 is 35% lenient / 4% strict vs 0.80+ 75-100%; same direction in every subject and system type. (2) AP -> K-12 hub: 29% lenient (level mismatch). (3) grade gap: |grade_delta|>=3 is 35% lenient, 2% strict. (4) topic/operation-word overlap without skill match ("compare", "area", "angles", "algorithm") and level mismatch dominate the N's at high cosine. Lexical Jaccard is also predictive (AUC 0.81 lenient) but is mostly verbatim-adoption, not used.
- **Lever chosen: cosine floor 0.75** (flag, not delete, edges below; `scripts/apply_cosine_floor.py`, reversible via `--revert`, marker ` | COSINE-FLOOR<0.75` in notes; guarded by `tests/test_cosine_floor.py`). Picked because it is the single free parameter that reaches the 90% lenient bar on held-out data (tuned on half the gold, reported on the other half, 200 random stratified splits; floor chosen median 0.76, IQR 0.74-0.76). Held-out: strict 33% -> 46%, lenient 79% -> 91% (5th-95th pct gain +5..+20 lenient). Canonical split seed 0: 34/79 -> 52/96. Grid over (LLM score floor, |grade delta| cap, cosine floor) is in `scripts/crosswalk_tune.py`; combos barely beat cosine alone and lose more coverage.
- **Coverage cost (the honest part):** standards with >=1 unflagged hub link 58.3% -> 41.9% (math 55.8%, science 39.8%, ELA 58.2%, SS 14.4%, CS 19.6%); 56,169 edges (33%) newly flagged. Curve: floor 0.72 -> 51.9% cov (est. lenient ~85%); 0.74 -> 45.2%; 0.75 -> 41.9%; 0.76 -> 38.8%; 0.78 -> 32.9%; 0.80 -> 28.0%. Edges remain queryable with `include_flagged=true`.
- **France:** 456 unscored fr-men edges scored with the repo's 1-5 prompt via 8 sonnet batches (scores: 5:39, 4:168, 3:141, 2:92, 1:16; 108 flagged <=2) and applied to the copy with `score_batch.py apply`. Fixed a Python 3.14 argparse crash in `score_batch.py` (`%` in help).
- **Cost:** 19 sonnet subagent calls total (10 labelers, 1 adjudicator, 8 France scorers), ~1.5M tokens; no per-edge API calls, no opus.
- **Not done / options:** re-scoring the 0.70-0.75 band blind with Claude (56k edges, ~1,100 batch calls at 50/call) could recover the ~35% of it that is lenient-correct; untested because the gold labeler is the same model (circular). Per-system/AP-specific floors; `nlp_pass` DEFAULT_THRESHOLD still 0.70 (new systems need the script re-run).
- Tests on the copy: `DB_PATH=~/.standardgraph/common_core_quality.db uv run --directory packages/common-core pytest ../../tests -q` -> 89 passed.

## 2026-10-19 - world-coverage pass (branch `world-coverage`, worktree ../standardgraph-world)

**Measuring unit:** `scripts/coverage_report.py` (run: `DB_PATH=~/.standardgraph/common_core.db uv run --directory packages/common-core python ../../scripts/coverage_report.py`).
Enrollment snapshot `data/world_enrollment.csv` = World Bank WDI SE.PRM.ENRL + SE.SEC.ENRL (UNESCO UIS), latest year per country, fetched 2026-10-19; gold sample `data/crosswalk_gold.csv` (52 hand-labelled math->ccss edges).

**Baseline (v1.6.2 DB, 175,738 std / 310 systems / 208,442 crosswalks):**
- Headline: **41.4%** of world K-12 pupils (585M of 1,415M) live in a country with a math curriculum in the DB; 33 countries. Science/ELA: 15 countries, 13.5%. Social studies 2 countries 4.4%. CS/arts/world-languages: US only, 3.5%.
- Hub crosswalk coverage (standards with >=1 crosswalk to subject hub): math 79.9%, science 58.1%, ELA 76.5%, social studies 32.0%, CS 36.8%; all 61.2%.
- Crosswalk precision (n=52, 4 intl math systems, single rater Claude): strict 37%, lenient (incl. partial) 71%. Small sample; directional.
- Biggest math gaps by pupils: China 207M, Indonesia 57M, Pakistan 45M, Bangladesh 32M, DR Congo 29M, Egypt 27M, Philippines 25M, Ethiopia 21M.
- Crosswalks are cosine over nomic-embed-text vectors (Ollama; local MacBook has the model), top-1 hub match >=0.70 via `crosswalk_engine/nlp_pass.py`; embeddings via `ingestion.shared.embed`.

**Phase 2/3 result (same day):** `docs/world-coverage-candidates.md` ranks 17 missing countries. Only **France** was truly low-lift (Etalab-2.0, text PDFs); everything else large is all-rights-reserved or unreachable (Turkey/Sri Lanka/Pakistan have good docs but no reuse terms; Vietnam/Russia have the best legal footing but need a human to fetch the official copy; China needs a legal read + OCR).
- Ingested `fr-men` (CP-3e, grades 1-9, 698 standards; lycee not done: education.gouv.fr annexes are behind Cloudflare). Pipeline: `scripts/france/parse_programmes.py` (deterministic) -> Claude translation -> `data/france_math_programmes.json` -> `ingestion.international.fetch_france` -> local-MacBook Ollama `nomic-embed-text` (no fleet needed, ~1 min) -> `relate.py --system fr-men` (new flag; leaves other systems alone) -> `nlp_pass --system fr-men`.
- Built into a copy: `~/.standardgraph/common_core_world-coverage.db` (176,436 std / 311 systems / 208,898 crosswalks). The live DB is untouched; tests: 85 pass + 2 skip on live DB, 87 pass on the copy.
- **After:** math pupils covered 41.35% -> 42.08% (34 countries); fr-men hub crosswalk coverage 65% (456/698; 0.70 cosine threshold), pulling math hub coverage 79.9% -> 79.6%; all-subject 61.2% unchanged. Gold precision (n=65 incl. 13 fr-men): strict 37%, lenient 72%; fr-men alone strict 5/13, lenient 10/13.
- Not done for fr-men: LLM quality scores on its 456 crosswalks (graph was 100% scored; now 456 unscored), direct_family edges (belongs to `iberian_continental`).
- To ship: promote the copy to the live DB, score the new edges, bump counts in README/CLAUDE.md/server.json (`/stats`), then HF upload (Ian only).

## 2026-10-19 - release-prep pass (branch `release-prep`, worktree ../standardgraph-release)

No written pre-release checklist existed (CLAUDE.md only has the publish steps), so I derived one
from the README promises, the registry manifests and the MCP input surface.

**Done**
- Tests: baseline 75 pass / 2 fail (needed `DB_PATH`; main tree's `data/common_core.db` symlink is absent in worktrees). Fixed: tests now honor `DB_PATH`; two stale fixtures (`al-ss.HG.14.a`, `fl-cs.7.08` no longer have precomputed rows after quality flagging) repointed to live rows. After: **82 passed, 0 failed** (`DB_PATH=~/.standardgraph/common_core.db uv run --directory packages/common-core pytest ../../tests -q`).
- Security pass on the 6 MCP tools: all SQL parameterized (only f-string SQL is a constant clause / `?` placeholder lists); FTS query is letters-only; no user-supplied filesystem paths (`/concept-map` serves one fixed file); no secrets in tracked files (regex scan clean; no .env/.db tracked). Fuzzed ids/systems/subject with SQLi, traversal, NUL, 200k chars, RTL: all clean errors. Gap fixed: `search_standards` `limit` unbounded (1e9 returned 1,569 rows) and `query` unbounded -> clamped 1-50 / 2,000 chars. Tests added.
- `server.json` was stale (1.2.3, "154,000+ / 300") -> 1.6.1, 175,000+/310. `smithery.yaml` description was stale ("20,000+ math / 75+") -> fixed.
- Live DB matches docs: 175,738 standards, 310 systems, 208,442 crosswalks. `uv build` OK, `twine check` PASSED on sdist+wheel (built to scratch dir, nothing uploaded).

**Not touched (dirty on main tree, another session's):** docs/overnight_source_decomposition_report.md, uv.lock, .claude/*, docs/spec_map_standard_scores.md.

**Ian-only steps, in order**
1. Merge `release-prep` into main (`git checkout main && git merge release-prep`) once the main tree's dirty files are settled.
2. Bump version: server code changed (search clamp) so 1.6.2. Edit `packages/common-core/pyproject.toml`, `server.json` (both version fields), and rename `[Unreleased]` in CHANGELOG.md to `[1.6.2] - <date>`; commit.
3. `cd packages/common-core && uv build && uvx twine check ../../dist/standardgraph-1.6.2*` then `TWINE_PASSWORD=<pypi token> uvx twine upload --username __token__ ../../dist/standardgraph-1.6.2*` (rotate token after).
4. DB unchanged since 1.6.1: no HuggingFace upload needed.
5. Registry: `mcp-publisher login github && mcp-publisher publish` (reads server.json); Smithery re-sync from smithery.yaml.
6. `git tag v1.6.2 && git push origin main --tags`; then decide public/announce (repo visibility is Ian's call).
7. Ship before OER (per notes).
