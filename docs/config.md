# Configuration

linelore has no config file. Everything is flags or environment:

| Setting | How |
|---|---|
| GitHub token | `LINELORE_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, else `gh auth token`, else anonymous |
| GitHub Enterprise | `--api https://ghe.example.com/api/v3` or `LINELORE_API` |
| Remote to read | `--remote upstream` (default `origin`) |
| Ignore formatting commits | `.git-blame-ignore-revs` at repo root is used automatically; override with `--ignore-revs-file` |
| Colour | off when not a TTY, `--no-color`, or `NO_COLOR` set |

Anonymous use works on public repos (60 requests/hour; each lookup costs 2 calls). Linked issues need a token.
