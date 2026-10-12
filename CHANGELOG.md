# Changelog

## 0.2.0 – 2026-10-12
- **Line ranges.** `linelore file.py:10-30` blames the range, deduplicates commits (same sha once even when it owns many lines), and prints lore per unique commit in first-appearance order. `--json` adds `range` and a `commits[]` array; single-line `FILE:LINE` output is unchanged.
- **Follow moves and renames.** Blame runs with `-C -M` so lore follows code across renames and copies within a commit.
- **API response cache.** GitHub lookups are cached in memory for the process and on disk under `~/.cache/linelore` (or `$XDG_CACHE_HOME/linelore`), keyed by API host + request. Set `LINELORE_CACHE` to a directory to override, or to `off` / `0` / `none` to disable disk caching.
- **Promote Fixes/Closes/Resolves.** When GraphQL `closingIssuesReferences` is empty (common on older PRs), mentions like `Closes #6715` in the PR title or body are promoted to the fixes list.

## 0.1.1 – 2026-10-10
- Review comments that are not within a few lines of the blamed line are now labelled "elsewhere in this file" (or "outdated diff") instead of looking like they are about that line; JSON entries carry `near: true/false`.
- `--offline` now says "offline: showing local commit only" instead of the misleading "no GitHub remote".
- `--rev` no longer crashes when the file's directory does not exist in the working tree any more (e.g. `requests/adapters.py:250 --rev v2.31.0` after a move to `src/`).

## 0.1.0 – 2026-10-10
- First release: FILE:LINE → commit → PR → closing issues → mentions → nearby review comments. `--json`, `--offline`, `--rev`, `--repo`, `--api`, `.git-blame-ignore-revs`.
