# CONTEXT - StandardGraph

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
