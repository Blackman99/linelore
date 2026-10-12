# Configuration

linelore has no config file. Everything is flags or environment:

| Setting | How |
|---|---|
| GitHub token | `LINELORE_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, else `gh auth token`, else anonymous |
| GitHub Enterprise | `--api https://ghe.example.com/api/v3` or `LINELORE_API` |
| Remote to read | `--remote upstream` (default `origin`) |
| Ignore formatting commits | `.git-blame-ignore-revs` at repo root is used automatically; override with `--ignore-revs-file` |
| API response cache | Disk cache under `~/.cache/linelore` (or `$XDG_CACHE_HOME/linelore`). Set `LINELORE_CACHE=/path` to override, or `LINELORE_CACHE=off` to disable disk caching. In-memory cache is always on for the process. |
| Colour | off when not a TTY, `--no-color`, or `NO_COLOR` set |

Anonymous use works on public repos (60 requests/hour; each lookup costs a few calls, fewer when the cache hits). Linked issues via GraphQL need a token; without one, `Fixes`/`Closes`/`Resolves #N` in the PR body are still promoted to the fixes list.
