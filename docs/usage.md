# Usage

```bash
cd your-repo
linelore path/to/file.py:42          # the story behind line 42
linelore path/to/file.py:10-30       # a range: unique commits, each with its lore
git lore path/to/file.py:42          # same, as a git subcommand
linelore file.py:42 --rev v1.2.0     # blame as of a tag/commit
linelore file.py:42 --open           # …and open the PR/MR in your browser
linelore file.py:42 --json           # for scripts and editors
linelore file.py:42 --offline        # local commit only, no network
linelore file.py:42 --repo org/name  # when origin is a fork or mirror
linelore file.py:42 --forge gitlab   # a self-hosted forge whose name says nothing
```

GitHub, GitLab and Gitea/Forgejo are detected from the remote URL; see [Forges](forges.md) for self-hosted setups and tokens.

## What you get

1. **commit** – sha, date, author, summary (from `git blame -w -C -M`).
2. **PR** / **MR** – the pull request(s) the forge associates with that commit, with a description excerpt (template headings, links and `Signed-off-by` trailers stripped). GitLab merge requests show as `MR !123`; open and closed-unmerged ones are labelled as such.
3. **fixes** – issues the PR closes (GitHub GraphQL with a token, GitLab `closes_issues`, Gitea `Fixes`/`Closes`/`Resolves` references looked up one by one; otherwise `Fixes`/`Closes`/`Resolves #N` or issue URLs in the PR title/body are promoted).
4. **mentions** – other `#123` / `owner/repo#123` references in the PR body.
5. **review** – review comments on that file (GitLab: diff notes, with replies), the ones within 6 lines of your line first.

## Ranges

`file:10-30` blames every line in the inclusive range, **deduplicates commits** (the same sha once even when it owns many lines), and prints one lore block per unique commit in first-appearance order. When several commits came from the same PR, its story is printed once and later commits say "same PR as above". `--json` adds `range` and a `commits[]` array; single-line `FILE:LINE` JSON is unchanged.

## Open it in the browser

`--open` prints the lore as usual, then opens the PR or MR: the only one for a line, the most recently merged one for a range. With no PR (a direct push, or `--offline`) it opens the commit page instead. On a machine without a desktop (SSH, CI) it never starts a console browser; it prints the URL on stderr instead, so `--json --open` keeps stdout clean.

## Editor integration

`--json` prints one object: `forge` (`"github"`, `"gitlab"`, `"gitea"`, or `null` when unknown), `repo`, `blame`, `pulls[]` (each with `issues`, `mentions`, `review_comments`) and `notes`. The shape is the same on every forge; on GitLab `number` is the MR iid. For a range it also includes `range` and `commits[]`. Bind it to a key in your editor, e.g. in Vim:

```vim
nnoremap <leader>w :echo system('linelore --no-color '.expand('%').':'.line('.'))<CR>
```
