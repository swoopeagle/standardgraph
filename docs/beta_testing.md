# Beta Testing Guide

Thanks for testing StandardGraph! This guide covers what to test, what to look for, and how to report issues.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/swoopeagle/standardgraph/main/install.sh | bash
```

Quit and reopen Claude Desktop after it finishes. Look for the 🔨 icon in a new conversation.

---

## What to test

### 1. Basic connectivity
Confirms the server is running and the database loaded correctly.

> *"List all available curriculum systems"*

**Expected:** A structured list of 75+ systems with standard counts per system.

---

### 2. Lookup by ID
Tests direct standard retrieval with prerequisites and successors.

> *"Look up CCSS.MATH.6.RP.A.3"*

> *"Look up TX.MATH.5.3.K"*

**Expected:** Full standard text, grade, domain, and related standards.

---

### 3. Semantic search
Tests natural language concept search within a system.

> *"Find CCSS standards on adding fractions with unlike denominators"*

> *"Search for Singapore MOE standards on geometric transformations in grade 5"*

> *"Find Ghana standards related to quadratic equations"*

**Expected:** Ranked list of matching standards with relevance scores.

---

### 4. Cross-system mapping
Tests the crosswalk engine — mapping a standard from one system to another.

> *"What's the Singapore equivalent of CCSS.MATH.6.RP.A.3?"*

> *"Map TX.MATH.5.3.K to the Australia national curriculum"*

> *"What does Ireland cover that's equivalent to CCSS grade 8 algebra?"*

**Expected:** Matched standards with confidence scores and grade alignment notes.

---

### 5. Concept progression
Tests how a topic develops across grade levels within a system.

> *"How does CCSS build fractions from grade 3 to 6?"*

> *"Show me the full algebra progression in Cambridge International"*

> *"When does place value appear in the IB MYP?"*

**Expected:** Grade-ordered stages showing concept development.

---

### 6. Multi-system comparison
Tests Claude's ability to chain tool calls across systems.

> *"Compare how CCSS and Singapore MOE approach fractions in grade 4. Are they aligned?"*

> *"Which curriculum introduces quadratic equations earliest — CCSS, Cambridge, or IB?"*

> *"I'm a teacher moving from Ontario to Scotland. What should I know about the math curriculum differences?"*

**Expected:** Coherent comparison drawing on multiple systems.

---

## What to flag

Please note anything that seems off:

- **Wrong standards returned** — search results that clearly don't match the query
- **Missing systems** — a system you'd expect to be there that isn't
- **Broken mappings** — crosswalk results that are obviously wrong grade or topic
- **Errors** — any tool returning an error message instead of results
- **Slow responses** — anything taking more than ~30 seconds

## How to report

Open an issue at [github.com/swoopeagle/standardgraph/issues](https://github.com/swoopeagle/standardgraph/issues) with:
- What you asked Claude
- What you expected
- What actually happened (paste the response if possible)

---

## Known limitations

- Semantic search requires [Ollama](https://ollama.com) running locally with `nomic-embed-text`. If you don't have Ollama, `lookup_standard`, `list_systems`, and crosswalk lookups still work fine.
- Some international systems have partial coverage (India, Philippines, Japan secondary).
- Crosswalk mappings are NLP-generated, not human-verified. High confidence (≥0.85) is reliable; lower scores are suggestive only.
