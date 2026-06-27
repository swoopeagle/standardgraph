Check that all published numbers match the live database and flag any drift.

Run these queries:
```bash
sqlite3 ~/.standardgraph/common_core.db "SELECT COUNT(*) FROM standards;"
sqlite3 ~/.standardgraph/common_core.db "SELECT COUNT(DISTINCT system) FROM standards;"
ls -lh ~/.standardgraph/common_core.db
```

Then grep the current stated numbers from docs and package:
```bash
grep -n "157\|156\|298\|297\|1\.8\|1\.9" /Users/ianwang/projects/standardgraph/README.md
grep -n "157\|156\|298\|297\|1\.8\|1\.9" /Users/ianwang/projects/standardgraph/docs/install.md
grep -n "157\|156\|298\|297\|1\.8\|1\.9" /Users/ianwang/projects/standardgraph/docs/quickstart.md
grep -n "description" /Users/ianwang/projects/standardgraph/packages/common-core/pyproject.toml
```

Compare live DB values against every number found in docs. Report:
- ✓ for each number that matches
- ✗ for each mismatch with: file:line, stated value, actual value, suggested fix

If any mismatches found, ask the user if they want them fixed in place. If yes, apply edits, commit, and push.

Round the standards count down to the nearest thousand for doc display (e.g. 157,101 → "157,000+"). DB size: round to one decimal GB.
