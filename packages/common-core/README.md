# standardgraph

**20,000+ math standards across 75+ curriculum systems, accessible as a Claude MCP server.**

Covers the US (CCSS + all 50 states), Canada, Australia, UK, Singapore, Japan, New Zealand, Ireland, Hong Kong, India, Ghana, South Africa, Rwanda, Cambridge International, IB MYP/DP, and more — all cross-referenced to CCSS via NLP semantic similarity.

## Install (macOS)

```bash
curl -fsSL https://raw.githubusercontent.com/swoopeagle/standardgraph/main/install.sh | bash
```

Restart Claude Desktop and look for the hammer 🔨 icon.

## Manual setup

```bash
mkdir -p ~/.standardgraph
curl -L https://huggingface.co/datasets/swoopeagle/standardgraph/resolve/main/common_core.db \
     -o ~/.standardgraph/common_core.db
```

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "standardgraph": {
      "command": "uvx",
      "args": ["standardgraph"],
      "env": { "DB_PATH": "/Users/YOUR_USERNAME/.standardgraph/common_core.db" }
    }
  }
}
```

## Tools

- `search_standards` — find standards by concept description
- `lookup_standard` — fetch a standard by ID with prerequisites/successors
- `get_progression` — trace how a concept develops across grade levels
- `map_standard` — find the equivalent standard in another curriculum
- `list_systems` — see all indexed systems with live counts

Full documentation: https://github.com/swoopeagle/standardgraph
