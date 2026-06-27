# StandardGraph Quickstart

You've installed StandardGraph and you see the 🔨 icon in Claude Desktop. Here's how to get the most out of it.

---

## The five tools

StandardGraph gives Claude five tools. You never call them directly — just ask Claude a question in plain English and it picks the right one.

| Tool | What it does | When Claude uses it |
|---|---|---|
| `search_standards` | Find standards matching a concept | "Find NGSS standards on ecosystems in middle school" |
| `lookup_standard` | Fetch a standard by ID | "What does CCSS.MATH.6.RP.A.3 say?" |
| `get_progression` | Trace a concept across grade levels | "How does fraction understanding build from grades 3–6?" |
| `map_standard` | Find the closest equivalent in another curriculum | "What's the Singapore equivalent of this Texas standard?" |
| `list_systems` | Show all available curriculum systems | "What science curricula do you have?" |

---

## Your first five queries

Try these to get a feel for what's possible:

**1. Explore what's available**
```
List all math curriculum systems you have access to
```

**2. Search by concept**
```
Find CCSS math standards on ratios and proportional reasoning in grade 6
```

**3. Trace a concept across grades**
```
How does CCSS build fraction understanding from grade 3 to grade 5?
```

**4. Look up a specific standard**
```
What is CCSS.MATH.8.EE.B.5 and what comes before and after it?
```

**5. Map across curricula**
```
What's the closest Ontario equivalent to CCSS.MATH.5.NF.A.1?
```

---

## Reading crosswalk results

When you ask Claude to map a standard to another curriculum, it returns a confidence score:

| Score | Meaning | What to do |
|---|---|---|
| ≥ 0.90 | Strong match — same concept, aligned grade | Use with confidence |
| 0.85–0.89 | Good match — same concept, may differ by ±1 grade | Mention the grade difference |
| 0.75–0.84 | Plausible — related concept, scope may differ | Flag as "worth verifying" |
| < 0.75 | Weak — related but not equivalent | Treat as a starting point only |

These scores come from NLP similarity, not human review. For high-stakes decisions (student placement, curriculum adoption), have a subject-matter expert verify any mapping below 0.85.

---

## Practical examples by use case

### Curriculum alignment

*You're aligning your school's curriculum to CCSS and want to know what you already cover.*

```
I teach using the Ontario math curriculum. Which of my grade 5 standards align most closely with CCSS grade 5 math?
```

```
We use the IB MYP. Map our grade 6 algebra standards to CCSS so I can see where we're ahead or behind.
```

### Lesson planning across systems

*You're building a unit and want to see how different countries approach the same concept.*

```
How do CCSS, Singapore MOE, and the Australian curriculum each approach teaching fractions in grade 4? Show me the actual standard text.
```

```
I'm teaching quadratic functions. What do the AP Precalculus, IB DP, and CCSS high school standards say about this topic?
```

### Standards lookup and research

*You have a standard ID and want to understand it in context.*

```
Look up NGSS MS-LS2-4 and tell me what prerequisite concepts students should know first.
```

```
What Texas math standards cover probability and statistics in grades 6–8?
```

### International comparison

*You're working with students or schools from another country and need to understand equivalencies.*

```
A student is moving from the UK national curriculum (Year 9) to a US school. What CCSS math standards should they have already covered?
```

```
How does Ghana's NACCA math curriculum compare to CCSS in terms of when algebra is introduced?
```

---

## Tips

**Be specific about grade and subject.** The database covers 157,000+ standards. The more context you give, the better the results.

- Vague: *"Find standards on writing"*
- Better: *"Find CCSS ELA standards on argumentative writing in grades 9–10"*

**Use standard IDs when you have them.** `lookup_standard` is fast and exact — no search needed.

**Chain queries for deeper analysis.** Claude can run multiple tools in one conversation:
```
Look up CCSS.MATH.6.RP.A.3, then find the closest equivalent in Singapore MOE, then show me how the concept develops across grades 6–8 in CCSS.
```

**Ask for grade delta when mapping.** When a match is found, ask Claude whether the concept is taught at the same grade level or earlier/later in the target curriculum — this is often the most useful insight.

---

## Add StandardGraph to a Claude Project

For ongoing curriculum work, paste the following into your Claude Project instructions (Settings → Projects → [your project] → Instructions). This tells Claude how to interpret results without you having to explain it every time.

```
You are a K-12 curriculum expert with access to StandardGraph — a database of 157,000+ standards across 298 curriculum systems in 50+ countries, covering Math, Science, ELA, Social Studies, Computer Science, Arts, and World Languages.

When the user asks about standards, use these tools:
- search_standards — when they describe a concept and want matching standards
- lookup_standard — when they cite a specific standard ID
- get_progression — when they ask how a topic develops across grade levels
- map_standard — when they want the equivalent standard in another curriculum
- list_systems — when they want to know which systems are available

Crosswalk confidence scores:
- ≥ 0.90: Strong match
- 0.85–0.89: Good match, note any grade difference
- 0.75–0.84: Plausible, flag as worth verifying
- < 0.75: Weak, treat as a starting point only

Always note: crosswalk mappings are NLP-generated, not human-verified. For high-stakes decisions, recommend expert review for any mapping below 0.85.
```

---

## Getting help

- Full install guide: [docs/install.md](install.md)
- Coverage details: [README](../README.md)
- Issues: [github.com/swoopeagle/standardgraph/issues](https://github.com/swoopeagle/standardgraph/issues)
