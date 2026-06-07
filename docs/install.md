# Installing StandardGraph

StandardGraph gives Claude access to 20,000+ math standards across 75+ curriculum systems — US (all 50 states + CCSS), Canada, Australia, UK, Singapore, Japan, New Zealand, Ireland, Hong Kong, India, Ghana, South Africa, Rwanda, Cambridge International, IB MYP/DP, and more.

## Requirements

- macOS (Windows/Linux support coming)
- [Claude Desktop](https://claude.ai/download)

That's it. The installer handles everything else.

## Install

Open Terminal and run:

```bash
curl -fsSL https://raw.githubusercontent.com/swoopeagle/standardgraph/main/install.sh | bash
```

The installer will:
1. Install [uv](https://docs.astral.sh/uv/) if you don't have it (~30 seconds)
2. Download the standards database (~200 MB)
3. Configure Claude Desktop automatically

Then **quit and reopen Claude Desktop**.

## Verify it's working

Open a new conversation in Claude and look for the hammer 🔨 icon in the toolbar. If it's there, StandardGraph is connected.

Try asking:
- *"List all available curriculum systems"*
- *"Search for standards on fractions in grade 4"*
- *"How does algebra develop from grade 6 to 8 in CCSS?"*

## Example queries

```
Compare how Singapore MOE and CCSS teach fractions in grade 4
```
```
What's the Ghana equivalent of CCSS.MATH.6.RP.A.3?
```
```
Find all standards on geometric transformations in the IB MYP
```
```
How does place value develop from kindergarten to grade 5 in CCSS?
```
```
Map TX.MATH.5.3.K to the Australia national curriculum
```

## Notes

- **Crosswalk and lookup tools** work fully offline (no Ollama needed)
- **Semantic search** (`search_standards`, `get_progression`) requires [Ollama](https://ollama.com) running locally with the `nomic-embed-text` model
- The database updates nightly — re-run the installer to get the latest version

## Uninstall

Remove the database and config entry:

```bash
rm -rf ~/.standardgraph
```

Then open `~/Library/Application Support/Claude/claude_desktop_config.json` and remove the `standardgraph` entry.

## Source

[github.com/swoopeagle/standardgraph](https://github.com/swoopeagle/standardgraph)
