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

## `world_map.html` — global crosswalk reach (the breadth story)

Every curriculum system crosswalks into the five shared hubs (CCSS math/ELA, NGSS, C3,
CSTA), so **28 countries across 7 regions are mutually interoperable through the hubs**.
A world map (D3 geo + land basemap) with a dot per country sized by mapping volume;
**click a country to fan out arcs to every other curriculum it can map to**. Offline
single file. The "look how expansive the mapping gets between countries" view.

## `crosswalk_chord.html` — country interoperability (animated, filterable)

The same 28 countries around a circle; ribbons = the number of hub subjects two countries
share. **Filter by region** (All / North America / Latin America / Europe / Asia-Pacific /
Sub-Saharan Africa) — the chord **morphs with a smooth transition** to that region's internal
interconnection (e.g. Europe → the 9 European curricula, Asia-Pacific → Singapore/Japan/
Korea/HK/NZ/Australia). **▶ autoplay** cycles the regions hands-free (the intro animation).
Hover a country to isolate its links.

Note on the axis: country-to-country interoperability currently runs through **CCSS Math**
— the only hub with multi-country coverage. ELA / science / social-studies / CS crosswalks
are US-only today (the hubs are US frameworks), so *region* is the meaningful filter axis for
this view, not subject. Extending international science→NGSS crosswalks is a documented
follow-up that would make a subject filter here meaningful too.

Regenerate both crosswalk views (defaults to dev DB; pass prod for the shipped copy):

```bash
uv run python scripts/viz/export_crosswalk_viz.py ~/.standardgraph/common_core.db docs/viz
```

`scripts/viz/export_crosswalk_viz.py` supplements missing country metadata, geolocates
each country, and inlines the D3 + world-land topojson + topojson-client (all offline).
