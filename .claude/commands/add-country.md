Add a new country's curriculum (or extend/fix an existing one) to StandardGraph. This is the
battle-tested playbook from the 2026-07 Africa expansion (10 new systems, 3 extended, 5,814+
new standards) — follow it instead of re-deriving the approach from scratch.

**The single highest-leverage decision in that session:** do extraction with Claude/subagents
directly, not local Ollama models (gemma4, qwen). Local models got fooled by corrupted fonts,
rotated/reversed text, and multi-column tables — Claude subagents caught and fixed all of these
autonomously (one installed Tesseract OCR mid-task on CID-encoded garbage; another
reverse-engineered a custom font substitution cipher; another caught a mislabeled source URL by
actually reading the page). Reserve the Ollama fleet for what it's actually good at:
`nomic-embed-text` embeddings, which are mechanical and don't need judgment. Only fall back to
the fleet for extraction if the user explicitly asks for it.

## Phase 1 — Research

1. Identify the country's official curriculum body (ministry of education / curriculum
   development center / examinations council).
2. Find real PDF URLs for the target subject/grade-bands via WebSearch. Before trusting a URL,
   WebFetch it and read page 1 to confirm it's actually the claimed subject — a government site
   mislabeling its own links is common. (Nigeria's given "math" URL turned out to be the
   *National Values Curriculum* — caught only by reading the extracted text.)
3. Work out grade-band coverage (primary/secondary/A-level etc.) and map it to this project's
   convention: grades are plain strings `"1"`–`"9"`, `"K"` for kindergarten/reception/Grade R,
   `"HS"` for any 10-12/A-level/upper-secondary content. Only set `grade_band="9-12"` when
   `grade="HS"` — every other grade gets `grade_band=NULL`.
4. Pick a system code: lowercase, hyphenated, country-prefixed (`na-nied`, `ke-kicd`,
   `zw-zimsec`). Check it doesn't collide:
   `sqlite3 ~/.standardgraph/common_core.db "SELECT DISTINCT system FROM standards WHERE system LIKE '<prefix>%';"`
5. Crosswalk hub: currently only math→`ccss` is wired for new systems. Science/ELA/social
   studies extractions are fine to add but won't get a crosswalk pass unless you extend
   `crosswalk_engine/nlp_pass.py`'s hub logic first.

## Phase 2 — Extraction

For each country/subject, spawn one background subagent via the Agent tool (`run_in_background:
true`, several in parallel is fine — they're independent). Give each one:

- The source PDF URL(s), or an already-downloaded path if you have one
- The exact schema for `standards` + `keywords` (copy straight from
  `sqlite3 ~/.standardgraph/common_core.db ".schema standards"` — don't paraphrase it)
- The system code, subject, and grade mapping from Phase 1
- Extraction rules: extract specific learning objectives/outcomes/competencies; exclude
  assessment guidance, teaching activities, resource lists, and time allocations
- Instructions to write directly into an **isolated per-system shard file**
  (`/tmp/shards/{system}.db`) via Python's `sqlite3` module — not the master DB, not a shared
  file another agent might also touch
- A request to report final counts *and* 2-3 sample `standard_text` values, so you can eyeball
  quality without re-reading the source PDF yourself

**Never let two agents share one shard file.** In the session this playbook comes from, two
agents wrote to the same file concurrently and one silently clobbered 70% of the other's rows —
caught only because the row count was checked directly afterward, not because either agent
reported a problem. One file per agent, always.

### Known PDF gotchas — worth mentioning to every extraction subagent up front

1. **Reversed/mirrored text.** Some government PDFs (education.gov.za CAPS docs, ZIMSEC) store
   glyphs character-reversed inside rotated tables. Detect it by counting whitespace-tokens that
   match a small set of common English words forward vs. reversed on a given line; if reversed
   wins, reverse each token's characters back. Do this per-line or per-token — a single document
   can mix normal and reversed lines on the same page.
2. **Corrupted/CID-encoded fonts.** `pdfplumber` returns `(cid:N)` placeholders instead of real
   text. Fix: render the page as an image (`pdf2image`) and OCR it with `pytesseract` at ~250
   DPI. Install tesseract first if needed (`brew install tesseract`).
3. **Downloads getting blocked or timing out.** Use
   `urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})` +
   `urllib.request.urlopen(req, timeout=60)` — several ministry sites reject requests with no
   User-Agent header, and a plain `urlretrieve` doesn't give you a clean timeout hook.
4. **Wrong subject at a given URL.** Confirmed in Phase 1, but worth re-checking once the
   subagent actually opens the PDF — official curriculum portals do mislabel their own links.

### Verify before trusting "done"

When a subagent reports completion, don't merge yet. Run this yourself against the actual shard
file:

```bash
sqlite3 /tmp/shards/<system>.db "
SELECT COUNT(*), COUNT(DISTINCT id),
       SUM(CASE WHEN standard_text IS NULL OR standard_text='' THEN 1 ELSE 0 END) as null_text,
       SUM(CASE WHEN domain IS NULL OR domain='' THEN 1 ELSE 0 END) as null_domain
FROM standards;"
```

`COUNT(*)` should equal `COUNT(DISTINCT id)`, and both null counts should be zero. This exact
check caught two real problems in the source session: a shard that lost rows to a concurrent
write, and an agent that was still genuinely working in the background — its "done" checkpoint
had been merged prematurely, and it kept going for over two hours before delivering the real
final count. Don't assume a stable-looking row count means an agent has stopped; only a completed
notification (with independent verification) means that.

## Phase 3 — Merge into master DB

1. Back the master DB up first — it's ~1.6GB, a plain `cp` is cheap insurance for a write that's
   otherwise hard to undo:
   ```bash
   cp ~/.standardgraph/common_core.db /tmp/common_core_pre_merge_$(date +%Y%m%d_%H%M%S).db
   ```
2. Merge each verified shard:
   ```bash
   sqlite3 ~/.standardgraph/common_core.db "
     ATTACH DATABASE '/tmp/shards/<system>.db' AS src;
     INSERT OR IGNORE INTO standards SELECT * FROM src.standards;
     INSERT OR IGNORE INTO keywords (standard_id, keyword, created_at)
       SELECT standard_id, keyword, created_at FROM src.keywords;
     DETACH DATABASE src;"
   ```
   `INSERT OR IGNORE` is safe here because a new country gets a fresh ID namespace — there's no
   collision risk with the existing 150k+ rows.
3. After every shard is merged, do one final sweep — compare each shard's row count against what
   actually landed in master:
   ```bash
   sqlite3 ~/.standardgraph/common_core.db "SELECT COUNT(*) FROM standards WHERE system='<system>';"
   ```
   If a shard has *more* rows than master, its data arrived after you merged (exactly what
   happened with Kenya in the source session) — merge the delta and re-run Phase 4 for that
   system only.

## Phase 4 — Pipeline (embed → relate → crosswalk → QC)

Run all of these from the repo root:

```bash
DB_PATH=~/.standardgraph/common_core.db OLLAMA_BASE_URL=http://<fleet-ollama-endpoint>:11434 \
  OLLAMA_MODEL=nomic-embed-text uv run python -m ingestion.shared.embed

DB_PATH=~/.standardgraph/common_core.db uv run python -m ingestion.shared.relate

DB_PATH=~/.standardgraph/common_core.db uv run python -m crosswalk_engine.nlp_pass --system <new-system>
# repeat --system once per new math system

DB_PATH=~/.standardgraph/common_core.db uv run python scripts/mcp_test.py
```

- `embed.py` only embeds standards missing an `embeddings` row, so it's safe to just re-run —
  no manual filtering needed.
- `relate.py`'s rebuild **must** stay scoped to `WHERE method='grade_heuristic'` in its DELETE.
  This project has a separate `llm_validated` prereq-graph pilot living in the same
  `standard_relationships` table — a few thousand rows of real human/LLM-validated work. An
  unscoped `DELETE FROM standard_relationships` silently destroys it. `grep -n "DELETE FROM
  standard_relationships" packages/ingestion/src/ingestion/shared/relate.py` before running, and
  confirm the `WHERE` clause is still there.
- `crosswalk_engine/nlp_pass.py` already UPSERTs and preserves any LLM-quality-scored notes on
  conflict, so it's safe to re-run per-system without a manual snapshot.
- Confirm QC still passes with the same or higher count and zero new failures before calling
  this release-ready.

## Phase 5 — Release

Use the `/release` command for this — it already covers version bump, build, PyPI upload,
GitHub push, and the HuggingFace DB push. One correction worth knowing going in: `huggingface-cli`
is deprecated and no longer works. Use the modern CLI instead:

```bash
export HF_TOKEN='<token>'
uvx --from huggingface_hub hf upload swoopeagle/standardgraph \
  ~/.standardgraph/common_core.db common_core.db --repo-type dataset
```

(Export the token rather than passing `--token "$HF_TOKEN"` inline — that flag had a quoting bug
that silently sent an empty bearer token in testing.)

Before bumping the version, refresh the description numbers in
`packages/common-core/pyproject.toml` to match reality:
```bash
sqlite3 ~/.standardgraph/common_core.db "SELECT COUNT(*) FROM standards;"
sqlite3 ~/.standardgraph/common_core.db "SELECT COUNT(DISTINCT system) FROM standards;"
```

Always remind the user to rotate both tokens immediately after use — never let them persist in
shell history or get echoed into logs; pass them as env vars, not positional args.

## Meta-lessons worth carrying into every run of this playbook

- **Verify, don't trust.** Every "done" self-report in the source session got checked with a
  direct SQL query before being acted on — that's what caught the Kenya straggler and the SA-ELA
  data loss. Extend the same skepticism to yourself: after any merge or pipeline step, check the
  actual row counts rather than assuming the last command succeeded.
- **Isolate concurrent work.** Shard files are cheap; a corrupted shared file is not. Give every
  parallel agent its own file, always.
- **Claude reads better than local models parse.** When a PDF is being difficult — reversed
  text, corrupted fonts, ambiguous tables — that's a signal to lean harder into direct reasoning
  (read the raw extracted text yourself, or let the subagent do so), not to retry the same weak
  extraction approach with more chunks or a different prompt.
