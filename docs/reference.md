# Command reference

```
linelore FILE:LINE|FILE:START-END [--rev REV] [--repo OWNER/REPO] [--remote NAME]
                                  [--forge {github,gitlab,gitea,forgejo}] [--api URL]
                                  [--ignore-revs-file PATH] [--json] [--open] [--offline]
                                  [--summarize] [--summarize-cmd CMD] [--no-color]
linelore demo [--json] [--summarize] [--summarize-cmd CMD]
```

`FILE:LINE` blames one line. `FILE:START-END` blames an inclusive range, deduplicates commits, and prints lore per unique commit.

| Flag | Meaning |
|---|---|
| `--rev REV` | blame as of a tag or commit |
| `--repo OWNER/REPO` | the repo on the forge (GitLab: `GROUP/SUBGROUP/PROJECT`); default from the remote |
| `--remote NAME` | remote to read the forge and repo from (default `origin`) |
| `--forge NAME` | `github`, `gitlab`, `gitea` or `forgejo` (the Gitea API; messages say Forgejo); default detected from the remote host |
| `--api URL` | API base for self-hosted forges; `/api/v4` implies GitLab, `/api/v1` Gitea |
| `--ignore-revs-file PATH` | skip formatting commits (default `.git-blame-ignore-revs`) |
| `--json` | one JSON object on stdout |
| `--open` | open the PR/MR (newest merged for a range; the commit page if there is none); prints the URL on stderr when there is no browser |
| `--offline` | local git only, no network |
| `--summarize` | after the facts, add a summary from your own model command (`LINELORE_SUMMARIZE_CMD`), labelled as model-generated; JSON gets a separate `model_summary` field. See [Summaries](summaries.md) |
| `--summarize-cmd CMD` | the command to summarize with (reads a prompt on stdin, prints the answer); implies `--summarize` |
| `--no-color` | plain text |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | printed the lore (even if no PR was found) |
| 1 | git error (not a repo, bad line, unknown file) |
| 2 | usage error |
| 3 | forge lookup failed (network, rate limit, 401/404); local commit info printed anyway |
| 4 | `--summarize` command failed (missing, non-zero exit, timeout, no output); the facts were printed anyway |
