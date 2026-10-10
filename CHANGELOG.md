# Changelog

## Unreleased
- Review comments that are not within a few lines of the blamed line are now labelled "elsewhere in this file" (or "outdated diff") instead of looking like they are about that line; JSON entries carry `near: true/false`.
- `--offline` now says "offline: showing local commit only" instead of the misleading "no GitHub remote".

## 0.1.0 – 2026-10-10
- First release: FILE:LINE → commit → PR → closing issues → mentions → nearby review comments. `--json`, `--offline`, `--rev`, `--repo`, `--api`, `.git-blame-ignore-revs`.
