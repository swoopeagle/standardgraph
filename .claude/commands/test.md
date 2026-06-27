Run the StandardGraph MCP test suite and report results.

Execute:
```bash
DB_PATH=~/.standardgraph/common_core.db uv run python scripts/mcp_test.py 2>&1
```

The suite has 272 tests across 14 sections:
1. list_systems
2. search_standards — subject coverage
3. search_standards — edge cases
4. get_progression
5. lookup_standard
6. map_standard
7. Data integrity (embeddings, relationships, nulls, duplicates)
8. Prerequisites & successors
9. Grade range filters
10. Precomputed crosswalk paths
11. US Math — all 51 states, searches, and crosswalks (rigorous)
12. AP Math — all 4 systems, searches, and crosswalks (rigorous)
13. IB Math — MYP/DP counts, searches, progression, crosswalk (rigorous)
14. Cross-system comparisons (AP↔IB↔Cambridge)

After running:
- Report the summary line (N passed | N failed | N warnings | N total)
- If there are failures, show each failed check with its detail message
- If all pass, confirm "272/272 — all clear"
- If performance checks are borderline (list_systems > 4s), note it as a watch item
