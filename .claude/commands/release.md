Release a new version of StandardGraph to PyPI (and optionally HuggingFace).

Steps to follow in order:

1. Read the current version from `packages/common-core/pyproject.toml`
2. Ask the user what the new version should be (patch/minor/major bump, or explicit string)
3. Update the version in `packages/common-core/pyproject.toml`
4. Run `cd /Users/ianwang/projects/standardgraph/packages/common-core && uv build` — confirm it succeeds and note the output dist files
5. Ask the user for their PyPI token (remind them to rotate it immediately after use)
6. Run: `uvx twine upload --username __token__ /Users/ianwang/projects/standardgraph/dist/standardgraph-{VERSION}*` with the token as TWINE_PASSWORD env var
7. Commit the version bump: `git add packages/common-core/pyproject.toml && git commit -m "Bump version to {VERSION}"`
8. Push to GitHub: `git push origin main`
9. Ask: "Did the DB change since last release? If yes, upload to HuggingFace."
10. If yes: ask for HuggingFace token, then run:
    `uvx huggingface-cli upload swoopeagle/standardgraph ~/.standardgraph/common_core.db common_core.db --repo-type dataset`
    with the token as HF_TOKEN env var. Remind to rotate token.
11. Run `/stats` to verify docs numbers match the live DB.
12. Report: PyPI URL, GitHub commit, and whether HF was updated.

Important: ALWAYS remind the user to rotate any tokens shared in chat. Tokens should never persist in shell history — pass them via env vars, not positional args.
