"""End-to-end evaluation — Claude API + live MCP server via stdio transport.

Spawns the standardgraph server as a subprocess, lets Claude drive real tool calls,
then evaluates: (1) did Claude pick the right tool(s)? (2) does the answer contain
expected content? (3) Gemma judges overall quality.

Cost: ~$0.25–0.50 for a full run of 12 scenarios (claude-sonnet-4-6).

Usage:
  export ANTHROPIC_API_KEY=sk-ant-...
  uv run --group eval python scripts/eval/e2e_claude_test.py
  uv run --group eval python scripts/eval/e2e_claude_test.py --no-judge    # skip Gemma
  uv run --group eval python scripts/eval/e2e_claude_test.py --scenario 3  # one scenario
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT    = Path(__file__).parent.parent.parent
DB_PATH = ROOT / "data" / "common_core.db"
GEMMA_STUDIO_URL   = "http://169.254.1.1:11434/api/generate"
GEMMA_STUDIO_MODEL = "gemma4:31b-it-q8_0"
GEMMA_LOCAL_URL    = "http://localhost:11434/api/generate"
GEMMA_LOCAL_MODEL  = "gemma4:26b"
CLAUDE_MODEL = "claude-sonnet-4-6"

_OK   = "\033[32m OK \033[0m"
_FAIL = "\033[31mFAIL\033[0m"
_PART = "\033[33mPART\033[0m"
_ERR  = "\033[35m ERR\033[0m"
_SKIP = "\033[90mSKIP\033[0m"
_DIM  = "\033[90m"
_RST  = "\033[0m"


# ── Scenarios ─────────────────────────────────────────────────────────────────

SCENARIOS: list[dict[str, Any]] = [
    # ── Single-tool: search ────────────────────────────────────────────────────
    {
        "name": "TX Grade 4 multiplication",
        "prompt": "What are the Grade 4 multiplication standards in Texas TEKS?",
        "expect_tools": ["search_standards"],
        "expect_in_answer": ["TX", "multiplication", "4"],
    },
    {
        "name": "NGSS Grade 5 ecosystems",
        "prompt": "Find NGSS Grade 5 standards about food webs and energy flow in ecosystems.",
        "expect_tools": ["search_standards"],
        "expect_in_answer": ["NGSS", "5", "ecosystem"],
    },
    {
        "name": "CSTA CS Grade 6 algorithms",
        "prompt": "What CSTA standards cover loops, iteration, and algorithmic thinking in middle school?",
        "expect_tools": ["search_standards"],
        "expect_in_answer": ["csta", "algorithm"],
    },

    # ── Single-tool: lookup ────────────────────────────────────────────────────
    {
        "name": "Lookup CCSS fraction standard",
        "prompt": "Look up CCSS standard CCSS.MATH.5.NF.A.1 and explain what it covers.",
        "expect_tools": ["lookup_standard"],
        "expect_in_answer": ["5.NF.A.1", "fraction"],
    },

    # ── Single-tool: progression ───────────────────────────────────────────────
    {
        "name": "CCSS fractions progression",
        "prompt": "How does the concept of fractions develop across Grade 3 to Grade 5 in CCSS?",
        "expect_tools": ["get_progression"],
        "expect_in_answer": ["3", "4", "5", "fraction"],
    },
    {
        "name": "NGSS evolution K-12",
        "prompt": "Show me how evolution and natural selection builds from kindergarten through high school in NGSS.",
        "expect_tools": ["get_progression"],
        "expect_in_answer": ["evolution", "NGSS"],
    },

    # ── Single-tool: map ──────────────────────────────────────────────────────
    {
        "name": "SG to CCSS crosswalk",
        "prompt": "What is the CCSS equivalent of Singapore standard SG_MOE.MATH.7.N7.7.2?",
        "expect_tools": ["map_standard"],
        "expect_in_answer": ["CCSS", "SG_MOE"],
    },
    {
        "name": "CA sci to NGSS",
        "prompt": "Map California Grade 5 science standard CA.SCI.5-PS3-1 to its NGSS equivalent.",
        "expect_tools": ["map_standard"],
        "expect_in_answer": ["NGSS", "PS3"],
    },

    # ── Multi-tool: Claude must chain calls ────────────────────────────────────
    {
        "name": "Compare JP and IN fractions (multi-search)",
        "prompt": "Compare how Japan (MEXT) and India (NCERT) teach fractions in Grade 4. Search both systems.",
        "expect_tools": ["search_standards"],  # expect it called twice
        "expect_in_answer": ["Japan", "India"],
        "expect_min_tool_calls": 2,
    },
    {
        "name": "TX to CCSS then explain (map + lookup)",
        "prompt": "Find the CCSS equivalent of TX.MATH.4.4.B, then look up that CCSS standard and explain what it means.",
        "expect_tools": ["map_standard", "lookup_standard"],
        "expect_in_answer": ["TX.MATH.4.4.B", "CCSS"],
        "expect_min_tool_calls": 2,
    },
    {
        "name": "TX vs CA Grade 8 algebra (multi-search)",
        "prompt": "Compare Texas and California Grade 8 algebra standards. What does each state expect students to know?",
        "expect_tools": ["search_standards"],
        "expect_in_answer": ["Texas", "California"],
        "expect_min_tool_calls": 2,
    },

    # ── Single-tool: list_systems ─────────────────────────────────────────────
    {
        "name": "List available systems",
        "prompt": "What curriculum systems do you have available? I'm interested in what international systems are indexed.",
        "expect_tools": ["list_systems"],
        "expect_in_answer": ["sg-moe", "cambridge"],
    },
]


# ── MCP + Claude interaction ──────────────────────────────────────────────────

def _mcp_tool_to_anthropic(tool) -> dict:
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.inputSchema,
    }


async def run_scenario(session, claude, anthropic_tools: list[dict],
                       scenario: dict, verbose: bool = False) -> dict:
    """Drive one full Claude conversation with MCP tool execution."""
    from anthropic.types import ToolUseBlock

    messages = [{"role": "user", "content": scenario["prompt"]}]
    tool_calls_made: list[dict] = []
    final_answer = ""
    api_error = ""

    try:
        for _ in range(6):  # max 6 round-trips (generous for multi-tool scenarios)
            response = claude.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1024,
                tools=anthropic_tools,
                messages=messages,
            )

            if response.stop_reason != "tool_use":
                final_answer = " ".join(
                    b.text for b in response.content if hasattr(b, "text")
                )
                break

            # Collect tool calls from this turn
            tool_use_blocks = [b for b in response.content if isinstance(b, ToolUseBlock)]
            tool_results = []

            for block in tool_use_blocks:
                tool_calls_made.append({"name": block.name, "input": block.input})
                if verbose:
                    print(f"       → {block.name}({json.dumps(block.input)[:120]})")

                mcp_result = await session.call_tool(block.name, block.input)
                result_text = (
                    mcp_result.content[0].text
                    if mcp_result.content else "{}"
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

    except Exception as e:
        api_error = str(e)

    return {
        "tool_calls": tool_calls_made,
        "final_answer": final_answer,
        "error": api_error,
    }


# ── Deterministic checks ──────────────────────────────────────────────────────

def _check(scenario: dict, result: dict) -> tuple[bool, str]:
    if result["error"]:
        return False, f"API error: {result['error']}"

    tool_names_called = [t["name"] for t in result["tool_calls"]]

    # Check expected tools were called
    for expected in scenario.get("expect_tools", []):
        if expected not in tool_names_called:
            return False, f"Expected tool '{expected}' was not called (got: {tool_names_called})"

    # Check minimum number of tool calls for multi-tool scenarios
    min_calls = scenario.get("expect_min_tool_calls", 1)
    if len(result["tool_calls"]) < min_calls:
        return False, f"Expected ≥{min_calls} tool calls, got {len(result['tool_calls'])}"

    # Check expected content in final answer
    answer_lower = result["final_answer"].lower()
    for phrase in scenario.get("expect_in_answer", []):
        if phrase.lower() not in answer_lower:
            return False, f"Expected '{phrase}' in answer"

    return True, ""


# ── Gemma judge ───────────────────────────────────────────────────────────────

_JUDGE_PROMPT = """\
You are evaluating whether Claude gave a good answer to a user's educational question
using a curriculum standards database.

User question: {prompt}
Claude's answer:
{answer}

Does Claude's answer satisfactorily address the user's question?
Reply ONLY: YES, PARTIAL, or NO
Then one sentence explaining why.
"""


def _gemma_judge(prompt: str, answer: str,
                 url: str = GEMMA_STUDIO_URL, model: str = GEMMA_STUDIO_MODEL) -> tuple[str, str]:
    if not answer.strip():
        return "NO", "Empty answer"
    snippet = answer[:1000]
    try:
        resp = httpx.post(url, json={
            "model": model,
            "prompt": _JUDGE_PROMPT.format(prompt=prompt, answer=snippet),
            "stream": False,
            "options": {"temperature": 0},
        }, timeout=90)
        resp.raise_for_status()
        raw = resp.json()["response"].strip()
    except Exception as e:
        return "ERR", str(e)

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    first = lines[0].upper() if lines else ""
    reason = lines[1] if len(lines) > 1 else raw
    if first.startswith("YES"):    return "YES", reason
    if first.startswith("PARTIAL"): return "PARTIAL", reason
    if first.startswith("NO"):     return "NO", reason
    return "PARTIAL", raw


# ── Main ──────────────────────────────────────────────────────────────────────

async def _run(scenario_filter: int | None, no_judge: bool, verbose: bool,
               local_judge: bool = False) -> int:
    judge_url   = GEMMA_LOCAL_URL   if local_judge else GEMMA_STUDIO_URL
    judge_model = GEMMA_LOCAL_MODEL if local_judge else GEMMA_STUDIO_MODEL
    from anthropic import Anthropic
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.")
        return 1

    server_env = {
        **os.environ,
        "DB_PATH": str(DB_PATH),
        "OLLAMA_BASE_URL": "http://localhost:11434",
    }

    server_params = StdioServerParameters(
        command="uv",
        args=["run", "standardgraph"],
        env=server_env,
    )

    scenarios = SCENARIOS
    if scenario_filter is not None:
        if scenario_filter < 1 or scenario_filter > len(SCENARIOS):
            print(f"ERROR: --scenario must be 1–{len(SCENARIOS)}")
            return 1
        scenarios = [SCENARIOS[scenario_filter - 1]]

    claude = Anthropic(api_key=api_key)

    passed = partial = failed = errors = 0

    judge_label = f"gemma4:26b (local)" if local_judge else "gemma4:31b (studio)"
    print("\n── E2E Claude+MCP evaluation ────────────────────────────────────────")
    print(f"  Model: {CLAUDE_MODEL}  |  Server: uv run standardgraph")
    if not no_judge:
        print(f"  Judge: {judge_label}")
    print(f"  {'#':<3} {'Scenario':<38} {'Tools called':<12} {'Det':>4} {'LLM':>4}")
    print(f"  {'-'*3} {'-'*38} {'-'*12} {'----':>4} {'----':>4}")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            mcp_tools_resp = await session.list_tools()
            anthropic_tools = [_mcp_tool_to_anthropic(t) for t in mcp_tools_resp.tools]

            for i, scenario in enumerate(scenarios, 1):
                real_i = SCENARIOS.index(scenario) + 1

                if verbose:
                    print(f"\n  [{real_i}] {scenario['name']}")
                    print(f"       Q: {scenario['prompt']}")

                result = await run_scenario(session, claude, anthropic_tools, scenario, verbose)

                det_ok, det_msg = _check(scenario, result)
                det_tag = _OK if det_ok else (_ERR if result["error"] else _FAIL)

                llm_verdict = llm_reason = ""
                llm_tag = _SKIP
                if not no_judge and not result["error"]:
                    llm_verdict, llm_reason = _gemma_judge(
                        scenario["prompt"], result["final_answer"],
                        url=judge_url, model=judge_model,
                    )
                    llm_tag = (
                        _OK   if llm_verdict == "YES"     else
                        _PART if llm_verdict == "PARTIAL" else
                        _ERR  if llm_verdict == "ERR"     else
                        _FAIL
                    )

                tool_summary = ", ".join(t["name"] for t in result["tool_calls"])[:12]
                short_name = scenario["name"][:36] + ".." if len(scenario["name"]) > 38 else scenario["name"]
                print(f"  {real_i:<3} {short_name:<38} {tool_summary:<12} [{det_tag}] [{llm_tag}]")

                if not det_ok or (llm_verdict and llm_verdict not in ("YES", "PARTIAL")):
                    if det_msg:
                        print(f"       FAIL: {det_msg}")
                    if llm_reason:
                        print(f"       LLM:  {llm_reason[:100]}")

                if verbose and result["final_answer"]:
                    print(f"       A: {_DIM}{result['final_answer'][:200]}{_RST}")

                if result["error"]:
                    errors += 1
                elif not det_ok:
                    failed += 1
                elif llm_verdict == "PARTIAL":
                    partial += 1
                else:
                    passed += 1

    total = len(scenarios)
    print(f"\n  {total} scenarios — {passed} passed, {partial} partial, {failed} failed, {errors} errors")
    print()
    return 0 if (failed + errors) == 0 else 1


def main() -> None:
    p = argparse.ArgumentParser(description="E2E eval: Claude API + live MCP server")
    p.add_argument("--no-judge", action="store_true", help="Skip Gemma LLM scoring")
    p.add_argument("--local-judge", action="store_true", help="Use local Ollama (gemma4:26b) instead of Mac Studio")
    p.add_argument("--scenario", type=int, default=None, metavar="N",
                   help=f"Run only scenario N (1–{len(SCENARIOS)})")
    p.add_argument("--verbose", action="store_true", help="Print tool calls and answer snippets")
    p.add_argument("--list", action="store_true", help="List all scenarios and exit")
    args = p.parse_args()

    if args.list:
        print(f"\n  {'#':<3} {'Scenario':<40} Multi-tool?")
        for i, s in enumerate(SCENARIOS, 1):
            multi = "yes" if s.get("expect_min_tool_calls", 1) > 1 else ""
            print(f"  {i:<3} {s['name']:<40} {multi}")
        print()
        return

    sys.exit(asyncio.run(_run(args.scenario, args.no_judge, args.verbose, args.local_judge)))


if __name__ == "__main__":
    main()
