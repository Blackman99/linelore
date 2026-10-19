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
| Empty-answer expiry | `LINELORE_CACHE_EMPTY_TTL` seconds (default 3600; `0` = don't keep them; anything that isn't a number ≥ 0 means the default). See [below](#cache). |
| Colour | off when not a TTY, `--no-color`, or `NO_COLOR` set |

Anonymous use works on public repos (GitHub: 60 requests/hour; each lookup costs a few calls, fewer when the cache hits). Linked issues via GraphQL need a token; without one, `Fixes`/`Closes`/`Resolves #N` in the PR body are still promoted to the fixes list.

## Cache

A commit's PR, its issues and its review comments rarely change once the PR is merged, so those answers are kept on disk for good and the second look at a commit costs no API calls.

Empty answers are different. "No PR for this commit" is often only true *so far*: you ran linelore while the commit was still on a feature branch, then opened the PR. So empty answers (no PR, no review comments, an issue that 404s) are trusted for one hour and then asked again. While one is in use, the note says so:

```console
  note    no pull request found for this commit (pushed directly?); cached 12 min ago (LINELORE_CACHE_EMPTY_TTL=0 to re-check)
```

```bash
LINELORE_CACHE_EMPTY_TTL=0 linelore src/app.py:42      # ignore cached empty answers, and don't store new ones
LINELORE_CACHE_EMPTY_TTL=86400 linelore src/app.py:42  # trust them for a day (slow forge, tight rate limit)
```

Whether a repo or commit exists at all is never cached, so "not pushed yet?" goes away as soon as you push. To start from scratch, delete the cache directory; nothing else lives there.
