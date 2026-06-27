Show the job run history across all pipeline machines.

SSH into both Mac minis and parse their log directories into a unified timeline.

Run on Mac mini 2:
```bash
ssh devos@100.101.100.96 "
  echo '=== MINI2 ===' &&
  for f in \$(ls -t ~/projects/intl-math-standards-mcp/logs/*.log 2>/dev/null); do
    fname=\$(basename \$f)
    size=\$(wc -l < \$f)
    modified=\$(stat -f '%Sm' -t '%Y-%m-%d %H:%M' \$f)
    # Detect outcome
    if grep -q 'ALL DONE' \$f 2>/dev/null; then outcome='✓ done'
    elif grep -q 'FAILED' \$f 2>/dev/null; then outcome='✗ failed'
    elif grep -q 'Total:.*mappings written' \$f 2>/dev/null; then outcome='✓ done'
    else outcome='? unclear'; fi
    # Detect job type
    if echo \$fname | grep -q 'overnight'; then jtype='overnight'
    elif echo \$fname | grep -q 'reingest'; then jtype='reingest'
    elif echo \$fname | grep -q 'resume'; then jtype='resume'
    else jtype='other'; fi
    # Standards count if present
    standards=\$(grep -oE '[0-9]+ standards' \$f 2>/dev/null | tail -1 || echo '')
    echo \"\$modified | \$jtype | \$outcome | \$standards | \$fname\"
  done
"
```

Run on Mac mini 3:
```bash
ssh devos@100.123.114.101 "
  echo '=== MINI3 ===' &&
  for f in \$(ls -t ~/projects/intl-math-standards-mcp/logs/*.log 2>/dev/null); do
    fname=\$(basename \$f)
    modified=\$(stat -f '%Sm' -t '%Y-%m-%d %H:%M' \$f)
    if grep -q 'ALL DONE' \$f 2>/dev/null; then outcome='✓ done'
    elif grep -q 'FAILED' \$f 2>/dev/null; then outcome='✗ failed'
    elif grep -q 'Total:.*mappings written' \$f 2>/dev/null; then outcome='✓ done'
    else outcome='? unclear'; fi
    if echo \$fname | grep -q 'overnight'; then jtype='overnight'
    elif echo \$fname | grep -q 'reingest'; then jtype='reingest'
    elif echo \$fname | grep -q 'resume'; then jtype='resume'
    else jtype='other'; fi
    standards=\$(grep -oE '[0-9]+ standards' \$f 2>/dev/null | tail -1 || echo '')
    echo \"\$modified | \$jtype | \$outcome | \$standards | \$fname\"
  done
"
```

Present the combined output as a clean table sorted by date (newest first):

| Date | Machine | Job type | Outcome | Standards |
|---|---|---|---|---|

Then note:
- Any failed jobs that should be re-run
- The most recent successful run on each machine
- Whether the two machines are in sync (same standards count)
