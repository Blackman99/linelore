# FAQ

**How is this different from GitLens / gh-blame.nvim?** Those live in one editor. linelore is a plain CLI with `--json`, so it works in any terminal, editor, or script, and it goes past the PR to closing issues and nearby review comments.

**The line points to a formatting commit.** Add that commit to `.git-blame-ignore-revs`; linelore uses it automatically.

**"no pull request found"** – the commit was pushed directly, came from a squash elsewhere, or your clone is shallow (`git fetch --unshallow`).

**Can I ask about a range of lines?** Yes: `linelore file.py:10-30`. Commits are deduplicated so each sha is shown once.

**Where does it cache API responses?** In memory for the process, and on disk under `~/.cache/linelore` (override or disable with `LINELORE_CACHE`).

**GitLab / Gitea?** Not yet; see the [roadmap](https://github.com/Blackman99/linelore/blob/main/ROADMAP.md).

**Does it send my code anywhere?** No. It sends the commit sha and repo name to the GitHub API, nothing else.
