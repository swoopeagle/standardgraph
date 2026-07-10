# StandardGraph visualizations

## `prereq_graph.html` — interactive CCSS-math prerequisite graph

A single, self-contained HTML file (D3 + data inlined — **works fully offline**,
no server or CDN needed). Open it in any browser.

- **Layout:** grade-layered K→HS (left to right); nodes coloured by the six top-level
  CCSS conceptual categories.
- **Edges:** HARD prerequisites solid; SOFT (background) togglable; **cross-domain edges
  highlighted** (orange) — the links the grade-adjacency heuristic structurally cannot make.
- **Interactions:** hover a standard for its text; **click a standard to trace its full
  learning path** (the `get_learning_path` tool, visualised — dims everything except the
  prerequisite chain); click empty space to reset.

Regenerate from a DB (defaults to the dev DB; pass the prod DB for the shipped copy):

```bash
uv run python scripts/viz/export_graph.py ~/.standardgraph/common_core.db docs/viz/prereq_graph.html
```

The generator (`scripts/viz/export_graph.py`) maps the 33 fine-grained CCSS domains to
6 categories, flags cross-domain edges, and inlines `scripts/viz/vendor/d3.v7.min.js`.
