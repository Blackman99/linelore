# FAQ

**How is this different from GitLens / gh-blame.nvim?** Those live in one editor. linelore is a plain CLI with `--json`, so it works in any terminal, editor, or script, and it goes past the PR to closing issues and nearby review comments.

**The line points to a formatting commit.** Add that commit to `.git-blame-ignore-revs`; linelore uses it automatically.

**"no pull request found"** – the commit was pushed directly, came from a squash elsewhere, or your clone is shallow (`git fetch --unshallow`).

**I just opened the PR and it still says "no pull request found".** That answer came from the cache; the note says how old it is. Empty answers are asked again after an hour, or right away with `LINELORE_CACHE_EMPTY_TTL=0 linelore FILE:LINE`. See [Cache](config.md#cache).

**Can I ask about a range of lines?** Yes: `linelore file.py:10-30`. Commits are deduplicated so each sha is shown once.

**Where does it cache API responses?** In memory for the process, and on disk under `~/.cache/linelore` (override or disable with `LINELORE_CACHE`). Empty answers such as "no PR yet" expire after an hour (`LINELORE_CACHE_EMPTY_TTL`).

**GitLab / Gitea / Forgejo / Codeberg?** Yes, since 0.3. The forge is read from your remote; see [Forges](forges.md) for self-hosted instances and tokens.

**Why are there no review comments on my gitlab.com repo?** gitlab.com only shows merge request discussions to signed-in users. Set `GITLAB_TOKEN` (a token with `read_api` is enough); without it linelore still shows the MR and the issues it closed, and says so in a note.

**A Gitea/Forgejo PR merged with a merge commit isn't found.** linelore looks up the merge commit locally, so make sure the branch you blame contains the merge (`git fetch`), and that the clone isn't shallow.

**Does it send my code anywhere?** No. It sends the commit sha and repo name to your forge's API (GitHub, GitLab or Gitea), nothing else. Tokens only go to the forge they belong to.
