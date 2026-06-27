# Installing StandardGraph

StandardGraph gives Claude access to 157,000+ education standards across 298 curriculum systems — Mathematics, Science, ELA, Social Studies, Computer Science, Arts, and World Languages. Covers all 50 US states plus major international curricula (Canada, UK, Australia, Singapore, Japan, IB, Cambridge, and more).

## Requirements

- macOS (Windows/Linux support coming)
- [Claude Desktop](https://claude.ai/download)
- **Optional but recommended:** [Ollama](https://ollama.com) for semantic search (see below)

## Install

Open Terminal and run:

```bash
curl -fsSL https://raw.githubusercontent.com/swoopeagle/standardgraph/main/install.sh | bash
```

The installer will:
1. Install [uv](https://docs.astral.sh/uv/) if you don't have it (~30 seconds)
2. Download the standards database (~1.8 GB)
3. Configure Claude Desktop automatically

Then **quit and reopen Claude Desktop**.

## Verify it's working

Open a new conversation in Claude and look for the hammer 🔨 icon in the toolbar. If it's there, StandardGraph is connected.

Try asking:
- *"List all available curriculum systems"*
- *"Search for standards on fractions in grade 4"*
- *"How does algebra develop from grade 6 to 8 in CCSS?"*

---

## Setting up Ollama (recommended)

StandardGraph works out of the box, but installing Ollama unlocks **semantic search** — the ability to find standards by concept rather than exact keywords. For example, a search for "equal sharing" surfaces fraction standards even when those words don't appear verbatim in the standard text.

Without Ollama, StandardGraph falls back to full-text keyword search, which still works well for known standard IDs and precise terms.

### 1. Install Ollama

```bash
brew install ollama
```

Or download the macOS app directly from [ollama.com](https://ollama.com).

### 2. Pull the embedding model

```bash
ollama pull nomic-embed-text
```

This downloads a ~274 MB model. It only needs to run once.

### 3. Start Ollama

```bash
ollama serve
```

Ollama can also start automatically at login — open the Ollama menu bar app and enable "Launch at Login."

### 4. Verify

```bash
ollama list
```

You should see `nomic-embed-text` in the output. StandardGraph detects Ollama automatically and switches to semantic search.

---

## Search modes

| Mode | When active | Best for |
|---|---|---|
| Semantic (embedding) | Ollama running with `nomic-embed-text` | Concept-based queries ("equal sharing", "rates of change") |
| Keyword (FTS) | Ollama not available | Known terms, standard IDs, subject-specific vocabulary |

Both modes return the same result format — you don't need to change how you query.

---

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

---

## Update

Re-run the installer to get the latest database:

```bash
curl -fsSL https://raw.githubusercontent.com/swoopeagle/standardgraph/main/install.sh | bash
```

---

## Uninstall

```bash
rm -rf ~/.standardgraph
```

Then open `~/Library/Application Support/Claude/claude_desktop_config.json` and remove the `standardgraph` entry under `mcpServers`.

---

## Troubleshooting

**🔨 icon not appearing in Claude Desktop**
- Make sure you fully quit and reopened Claude Desktop (not just closed the window)
- Check that the config was patched: `cat ~/Library/Application\ Support/Claude/claude_desktop_config.json` — you should see a `standardgraph` entry under `mcpServers`

**Search returns no results**
- If Ollama isn't running, keyword search takes over automatically — try more specific terms
- Confirm the database downloaded fully: `ls -lh ~/.standardgraph/` — the `.db` file should be ~1.8 GB

**Ollama not being detected**
- Make sure `ollama serve` is running (or the Ollama app is open in your menu bar)
- Confirm the model is available: `ollama list` should show `nomic-embed-text`

---

## Source

[github.com/swoopeagle/standardgraph](https://github.com/swoopeagle/standardgraph)
