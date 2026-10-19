---
description: linelore works with GitHub, GitLab and Gitea/Forgejo (Codeberg). How the forge is detected, which token each one reads, self-hosted setups, and what each forge can and can't tell you.
---

# Forges

linelore asks the forge that hosts your repo. It reads which one from the remote URL (`origin`, or `--remote NAME`), so on most repos you don't pass anything.

| Forge | Detected from | API it calls | Token (optional on public repos) |
|---|---|---|---|
| **GitHub**, GitHub Enterprise | `github.com`, `ssh.github.com`, hosts named `github.*` (GHES) | `https://api.github.com`, or `https://HOST/api/v3` | `LINELORE_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, else `gh auth token` |
| **GitLab**, self-managed | `gitlab.com`, `salsa.debian.org`, `gitlab.gnome.org`, `gitlab.freedesktop.org`, `invent.kde.org`, `framagit.org`, `gitlab.archlinux.org`, hosts named `gitlab.*` | `https://HOST/api/v4` | `GITLAB_TOKEN` |
| **Gitea**, **Forgejo** | `codeberg.org`, `gitea.com`, `code.forgejo.org`, hosts named `gitea.*` / `forgejo.*` | `https://HOST/api/v1` | `GITEA_TOKEN` or `FORGEJO_TOKEN` |

SSH aliases from `~/.ssh/config` such as `git@github-work:org/repo.git` are understood too.

## Self-hosted and unusual hosts

If the host name doesn't say what it is, linelore tells you instead of guessing:

```console
$ linelore src/app.py:42
...
  note    can't tell which forge git.example.com runs; pass --forge gitlab, --forge gitea or --forge github (plus --api URL if its API isn't at https://git.example.com/api/...)
```

```bash
linelore src/app.py:42 --forge gitlab                                   # API at https://git.example.com/api/v4
linelore src/app.py:42 --api https://git.example.com/gitlab/api/v4      # forge is inferred from /api/v4
linelore src/app.py:42 --forge gitea --api https://git.example.com/api/v1
linelore src/app.py:42 --api https://ghe.example.com/api/v3             # GitHub Enterprise
```

`--api` ending in `/api/v4` means GitLab and `/api/v1` means Gitea/Forgejo; anything else is GitHub. `--forge forgejo` is accepted as another name for `gitea` (same API). `LINELORE_API` still works for GitHub Enterprise; it is ignored for GitLab and Gitea remotes so a GHES setting can't send requests to the wrong place.

Tokens are only sent to the forge they belong to: `GITLAB_TOKEN` never goes to GitHub, and your GitHub token never goes to a GitLab or Gitea host. For a GHES host linelore asks `gh auth token --hostname HOST`.

## What each forge gives you

The output and the `--json` shape are the same on every forge; `forge` tells you which one answered (`"github"`, `"gitlab"` or `"gitea"`).

**GitHub.** Commit → PRs (`/repos/{o}/{r}/commits/{sha}/pulls`, finds squash and rebase merges) → closing issues (GraphQL `closingIssuesReferences`, needs a token; without one, `Fixes`/`Closes`/`Resolves #N` in the PR are promoted) → review comments on the file.

**GitLab.** Shown as `MR !123`. Commit → merge requests (`/projects/:id/repository/commits/:sha/merge_requests`) → issues the MR closes (`/merge_requests/:iid/closes_issues`) → diff notes from the MR discussions, including replies in each thread. Subgroups work (`group/sub/project`).

!!! note "gitlab.com and review comments"
    gitlab.com only shows MR discussions to signed-in users. Without `GITLAB_TOKEN` you still get the commit, the MR and the issues it closes, and a note says review comments were skipped. A personal access token with `read_api` is enough.

**Gitea / Forgejo.** Commit → PR (`/repos/{o}/{r}/commits/{sha}/pull`) → `Fixes`/`Closes`/`Resolves` references in the PR (Gitea has no "closes" API, so each referenced issue is looked up for its real title and state) → review comments (`/pulls/{n}/reviews`, then `/reviews/{id}/comments` for each review that has inline comments).

Reviews are read page by page (50 a page, following `X-Total-Count` or `Link`), so a long-running PR doesn't lose its later reviews. Two limits keep a huge PR from turning into hundreds of requests: up to 500 reviews (10 pages), and the inline comments of the newest 50 reviews that have any. When a PR goes past either one, a note says so, for example `note    PR #4521 has 812 reviews; only the first 500 were read for review comments`.

Gitea only links a PR to its *merge* commit. When the blamed commit came in through a merge commit, linelore finds that merge locally (`git rev-list --first-parent --ancestry-path`) and asks again, so old branch-merged PRs are found too. It never attributes a commit pushed straight to the main branch to a later merge.

Codeberg can take 10–20 seconds on a cold request. linelore waits up to 30 seconds (`LINELORE_TIMEOUT` to change it) and caches every answer, so the second look at the same commit is instant ("no PR" answers are re-checked after an hour; see [Cache](config.md#cache)).

## Errors you might see

| Message | What to do |
|---|---|
| `GitLab rate limit hit on gitlab.com; set GITLAB_TOKEN` | Set the token, or wait. Cached lookups don't count. |
| `Forgejo rejected the token (401 on codeberg.org); check FORGEJO_TOKEN` | The token is wrong or expired. |
| `group/project not found on gitlab.com (private? set GITLAB_TOKEN)` | Private repo without a token, or the wrong `--repo`. |
| `commit 3f9c2a71be isn't on codeberg.org/o/r (not pushed yet?)` | Push the commit, or check `--remote`. Shown as a note; exit code 0. |
| `https://… did not answer with JSON; is the API URL right?` | `--api` points at a web page; use the `/api/v4` or `/api/v1` URL. |

Lookup failures exit with code 3 and still print the local commit.
