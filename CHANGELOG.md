# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Withheld British Columbia (`ca-bc`), Finland (`fi-oph`) and Rwanda (`rw-reb`) pending reuse permission (no stated licence or all rights reserved), and Kenya (`ke-kicd`), Uganda (`ug-ncdc`) and Nigeria (`ng-nerdc`) (sources marked "All rights reserved", verified 2026-10-20), and Poland (`pl-men`, statute basis only, pending counsel). Listed in `data/withheld_systems.txt`, applied by `scripts/withhold_systems.py`: 6,677 standards and 36,717 crosswalks removed from the release DB.

### Added

- World-coverage scan 2 (see `docs/world-coverage-scan-2.md`): new subjects for au-acara (social studies, digital tech, arts, languages), uk-nc, gb-sco (social studies), es-lomloe (science, ELA, social studies, CS, arts, languages) and new systems `no-udir` (Norway LK20) (Norway). Poland (`pl-men`) was extracted but is withheld pending counsel. Database not yet re-released.
- France (`fr-men`): 698 mathematics outcomes for grades 1-9 (cycles 2-4), Etalab-2.0 source; hub crosswalks to CCSS. Database not yet re-released.
- `scripts/coverage_report.py`: world-coverage metrics (countries and pupils covered, hub crosswalk coverage, gold-sample precision).
- `relate.py --system` to rebuild one system's prerequisite edges.

## [1.6.2] - 2026-10-19

### Fixed

- `search_standards` now clamps `limit` to 1-50 and truncates `query` to 2,000 characters (previously an unbounded `limit` could dump the whole corpus).
- `server.json` (MCP registry manifest) version and description brought in line with the package (was 1.2.3 / 154k standards).
- Tests honor `DB_PATH` (worktree-friendly) and two stale precomputed-crosswalk fixtures were repointed to live rows; added hostile-input tests.

## [1.6.1] - 2026-07-18

### Added

- Completed LLM quality scoring for the entire crosswalk graph: all 208,442 crosswalks now carry a 1–5 score (100% coverage). This release scores the remaining 41,697 hub-centric edges (state→hub mappings, mostly ELA, science, and social studies) that v1.6.0 left unscored.

### Changed

- Hub-centric weak-edge flagging is gentler than the direct-family layer: only score-1 edges are flagged for suppression (hub score-2 edges are often valid but grade-shifted, and `map_standard` already ranks by quality score). Direct-family edges retain the score ≤2 flag.
- Server code is unchanged from v1.6.0; this is a data-only release (updated database on HuggingFace).

### Fixed

- Re-scored ~2,520 non-math hub crosswalk rationales that were generated with a math-oriented prompt, using a subject-neutral prompt. Scores were unaffected; this corrects confusing rationale text on ELA/science/social-studies edges.

## [1.6.0] - 2026-07-17

### Added

- Added LLM rubric quality scores (1–5) to direct-family curriculum crosswalk edges. Scored edges record their result in `notes` as `[LLM score N/5]`; all 88,944 direct-family edges are now scored (100% coverage), bringing the graph to 166,745 LLM-scored crosswalks overall.
- Weak direct-family edges (scores of 2/5 or below) are flagged so they are suppressed from default `map_standard` results.

### Fixed

- Corrected 2026-07 region metadata.

### Data

- The release dataset contains 175,738 standards across 310 curriculum systems, with 88,944 direct-family edges and approximately 208,442 crosswalk rows.
