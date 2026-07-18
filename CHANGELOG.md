# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.6.0] - 2026-07-17

### Added

- Added LLM rubric quality scores (1–5) to direct-family curriculum crosswalk edges. Scored edges record their result in `notes` as `[LLM score N/5]`; all 88,944 direct-family edges are now scored (100% coverage), bringing the graph to 166,745 LLM-scored crosswalks overall.
- Weak direct-family edges (scores of 2/5 or below) are flagged so they are suppressed from default `map_standard` results.

### Fixed

- Corrected 2026-07 region metadata.

### Data

- The release dataset contains 175,738 standards across 310 curriculum systems, with 88,944 direct-family edges and approximately 208,442 crosswalk rows.
