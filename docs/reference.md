# Command reference

```
linelore FILE:LINE|FILE:START-END [--rev REV] [--repo OWNER/REPO] [--remote NAME]
                                  [--ignore-revs-file PATH] [--json] [--offline]
                                  [--no-color] [--api URL]
linelore demo [--json]
```

`FILE:LINE` blames one line. `FILE:START-END` blames an inclusive range, deduplicates commits, and prints lore per unique commit.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | printed the lore (even if no PR was found) |
| 1 | git error (not a repo, bad line, unknown file) |
| 2 | usage error |
| 3 | GitHub lookup failed; local commit info printed anyway |
