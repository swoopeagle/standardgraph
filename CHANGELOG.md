# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
