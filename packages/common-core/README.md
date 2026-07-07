# standardgraph

<!-- mcp-name: io.github.swoopeagle/standardgraph -->

**154,000+ education standards across 300 curriculum systems, accessible as a Claude MCP server.**

Covers seven subjects — Mathematics, Science, ELA, Social Studies, Computer Science, Arts, and World Languages — across the US (CCSS + all 50 states), Canada, Australia, UK, Singapore, Japan, New Zealand, Ireland, Hong Kong, India, Ghana, South Africa, Rwanda, Cambridge International, IB MYP/DP, AP, and more. Standards are cross-referenced to subject hubs (CCSS for math, NGSS for science, etc.) via semantic similarity, with LLM quality scores on the strongest mappings.

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
