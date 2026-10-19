# Configuration

linelore has no config file. Everything is flags or environment:

| Setting | How |
|---|---|
| Forge | detected from the remote URL; `--forge github\|gitlab\|gitea` (or `forgejo`) to override. See [Forges](forges.md). |
| GitHub token | `LINELORE_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, else `gh auth token`, else anonymous |
| GitLab token | `GITLAB_TOKEN` (needed on gitlab.com for review comments) |
| Gitea / Forgejo token | `GITEA_TOKEN` or `FORGEJO_TOKEN` |
| Self-hosted API | `--api https://ghe.example.com/api/v3`, `--api https://gitlab.example.com/api/v4`, `--api https://git.example.com/api/v1`. `LINELORE_API` works for GitHub Enterprise. |
| Request timeout | `LINELORE_TIMEOUT` seconds (default 30; Codeberg can be slow on a cold request) |
| Remote to read | `--remote upstream` (default `origin`) |
| Ignore formatting commits | `.git-blame-ignore-revs` at repo root is used automatically; override with `--ignore-revs-file` |
| API response cache | Disk cache under `~/.cache/linelore` (or `$XDG_CACHE_HOME/linelore`), keyed by forge + API host + request. Set `LINELORE_CACHE=/path` to override, or `LINELORE_CACHE=off` to disable disk caching. In-memory cache is always on for the process. |
| Colour | off when not a TTY, `--no-color`, or `NO_COLOR` set |

Anonymous use works on public repos (GitHub: 60 requests/hour; each lookup costs a few calls, fewer when the cache hits). Linked issues via GraphQL need a token; without one, `Fixes`/`Closes`/`Resolves #N` in the PR body are still promoted to the fixes list.
