# CONTEXT - StandardGraph

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
