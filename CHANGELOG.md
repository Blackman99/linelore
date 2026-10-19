# Changelog

## 0.3.0 – 2026-10-19
- **GitLab.** gitlab.com and self-managed GitLab: commit → merge requests → the issues each MR closes (`closes_issues`) → diff notes from the MR discussions, replies included. Shown as `MR !4112`; subgroups (`group/sub/project`) work. Token: `GITLAB_TOKEN`. gitlab.com only shows discussions to signed-in users, so without a token review comments are skipped with a note instead of failing.
- **Gitea and Forgejo** (Codeberg, gitea.com, code.forgejo.org, self-hosted): commit → PR → `Fixes`/`Closes`/`Resolves` references looked up as real issues (title and state) → review comments. Token: `GITEA_TOKEN` or `FORGEJO_TOKEN`. Gitea only links a PR to its merge commit, so when a line came in through a merge commit linelore finds that merge locally and asks again (never blaming a later merge for a direct push).
- **Forge detection.** Read from the remote URL (known hosts, `gitlab.*` / `gitea.*` / `forgejo.*` / `github.*` names, `~/.ssh/config` aliases like `github-work`). Override with `--forge {github,gitlab,gitea,forgejo}`; `--api` for self-hosted, where `/api/v4` implies GitLab and `/api/v1` Gitea. Unknown hosts get a note saying which flag to pass instead of a request to the wrong API.
- **`--open`** opens the PR/MR in your browser after printing the lore: the most recently merged one for a range, the commit page when there is no PR (or with `--offline`). On a machine with no desktop it prints the URL on stderr instead of starting a console browser, so `--json --open` keeps stdout clean.
- **JSON** gains a top-level `forge` field (`"github"`, `"gitlab"`, `"gitea"` or `null`). Everything else keeps its shape on every forge.
- **Clearer errors.** Rate limits, 401s, missing repos and unpushed commits name the host and the token variable to set; an API URL that returns HTML says so; slow forges get a 30 s timeout (`LINELORE_TIMEOUT`). A commit that isn't on the forge yet is a note, not a failure. The exit-3 failure note no longer also claims "offline".
- **Nicer terminal output.** Open PRs read "still open" and closed-unmerged ones "closed without merging" (no more "merged ?"); URLs are dimmed; long PR bodies and review comments wrap to the terminal width (single lines when piped); excerpts drop template headings, markdown link targets and `Signed-off-by` trailers; in a range, a PR shared by several commits is told once ("same PR as above").
- **Fixes.** GitHub Enterprise GraphQL now goes to `/api/graphql` (was `/api/v3/graphql`); for GHES hosts the token comes from `gh auth token --hostname HOST`; promoted issue links use the right host instead of always github.com. Cache keys include the forge. `Fixes https://…/issues/N` URLs and nested `group/sub/project#N` refs are recognised.


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
