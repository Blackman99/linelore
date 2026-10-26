---
title: "git blame tells you who. Here's how to get the why."
description: How linelore follows a line of code from git blame to the commit, the pull request, the issues it closed and the review comments around it, with the exact GitHub API calls and real output.
---

# git blame tells you who. Here's how to get the why.

*October 2026 · [中文版](git-blame-says-who-not-why-zh.md) · Output below is from linelore 0.1.1. On 0.1.0, far-away review comments were not labelled and `--offline` printed a different note.*

You are reading `src/requests/adapters.py` in [psf/requests](https://github.com/psf/requests) and line 420 is a docstring line about the `verify` argument. Why does this code look like this? `git blame` answers:

```console
$ git blame -L 420,420 src/requests/adapters.py
a62a2d35d (Ian Stapleton Cordasco 2024-05-22 06:51:48 -0500 420)         * If ``verify`` is a string, (i.e., it is a user-specified trust bundle)
```

That is *who* and *when*. The commit message, "Allow for overriding of specific pool key params", is a summary of *what*. The *why* is somewhere else: in the pull request that merged the commit, in the bug report that pull request fixed, and in the review thread where somebody asked "why not do it the other way?". On GitHub that is three or four page loads per line, and most editor integrations stop at the commit.

That gap is the whole reason [linelore](https://github.com/Blackman99/linelore) exists. People keep asking how to recover the reasoning behind old code ([Ask HN](https://news.ycombinator.com/item?id=46726249), [HN](https://news.ycombinator.com/item?id=47368874)). Often the reasoning *was* written down. It's just one hop past `blame`.

## The same line, one hop further

```console
$ linelore src/requests/adapters.py:420
src/requests/adapters.py:420  * If ``verify`` is a string, (i.e., it is a user-specified trust bundle)
  commit  a62a2d35d9  2024-05-22  Ian Stapleton Cordasco
          Allow for overriding of specific pool key params
  PR #6716  Allow for overriding of specific pool key params  (@sigmavirus24, merged 2024-05-24)
          https://github.com/psf/requests/pull/6716
          “This re-enables the use case of providing a custom SSLContext via a Transport Adapter as broken in #6655 and reported in #6715 Closes #6715”
  fixes #6715  SSLV3_ALERT_HANDSHAKE_FAILURE after upgrade from 2.31.0 to 2.32.2 [closed]
          https://github.com/psf/requests/issues/6715
  mentions  psf/requests#6655
```

Now the story is readable: 2.32.2 broke custom `SSLContext`s passed through a transport adapter (#6715), the breakage came from #6655, and #6716 put the use case back. Every line of that output was fetched, not guessed. linelore never writes a summary of its own.

Here is a line where the reasoning lives in code review instead:

```console
$ linelore src/requests/adapters.py:75
src/requests/adapters.py:75  from .models import PreparedRequest
  commit  c0813a2d91  2024-03-03  Ian Stapleton Cordasco
          Use TLS settings in selecting connection pool
  PR #6655  Use TLS settings in selecting connection pool  (@sigmavirus24, merged 2024-03-11)
          https://github.com/psf/requests/pull/6655
          “Previously, if someone made a request with `verify=False` then made a request where they expected verification to be enabled to the same host, they would potentially reuse a connection where TLS had not been verified. This fixes that issue.”
  review  @nateprewitt (line 66): Not against this, but I think this is the first time we're introducing typing into Requests. I'm curious if we want to start that or push it into typeshed since this will be precedent for future inline typing?
  review  @sigmavirus24 (line 66): This is for a private method (that I fully anticipate people abusing) but we're not advertising things are typed and so it's not something I'm concerned with.
```

An import of `PreparedRequest` looks like noise until you see the review thread. It's there for a type annotation, the first inline typing in requests, and the maintainers talked about whether that should set a precedent.

![linelore on psf/requests](../assets/demo.gif)

## How the chain is built

linelore is about 350 lines of Python using only the standard library. Each hop is one well-defined step.

### 1. Line → commit (local git)

```text
git blame --porcelain -w -L 420,420 [--ignore-revs-file .git-blame-ignore-revs] [REV] -- src/requests/adapters.py
```

`--porcelain` gives a machine-readable header: the commit sha, the line number *in that commit's version of the file* (`orig_line`), the author, the time, the summary and the filename at that commit. `-w` ignores whitespace-only changes. If the repo has a `.git-blame-ignore-revs` file, linelore passes it automatically, so mass-reformat commits don't hide the real author. `--rev v2.31.0` blames the file as it was at a tag.

The owner/repo comes from the `origin` remote URL (SSH and HTTPS forms are both parsed). `--remote` and `--repo` override it.

### 2. Commit → pull request (REST)

```text
GET /repos/{owner}/{repo}/commits/{sha}/pulls
```

This endpoint returns the pull requests associated with a commit. It covers merge commits, squash merges and rebased commits, because GitHub records the association when the PR is merged. linelore keeps up to three PRs and reads the title, author, merge date and body. If the list is empty, the commit was probably pushed straight to the branch, and linelore says so instead of guessing.

### 3. Pull request → the issues it closed (GraphQL)

```graphql
query($o:String!,$r:String!,$n:Int!) {
  repository(owner:$o, name:$r) {
    pullRequest(number:$n) {
      closingIssuesReferences(first:10) { nodes { number title url state body } }
    }
  }
}
```

`closingIssuesReferences` is GitHub's own record of "this PR closes that issue", whether it was set with `Closes #N` in the body or linked by hand in the sidebar. REST has no equivalent, so this is the one GraphQL call. linelore also scans the PR body for every other `#N` and `owner/repo#N` and lists them as **mentions**. Mentions are often where the backstory lives: in the first example, #6655 is the change that caused the bug.

### 4. Pull request → review comments near the line (REST)

```text
GET /repos/{owner}/{repo}/pulls/{number}/comments?per_page=100
```

These are the inline review comments. linelore keeps comments on the same file and sorts them by distance from the blamed line. It compares against `orig_line`, the line's position in the commit's version of the file, because that is the coordinate system reviewers saw. In the second example the line is 75 today but was 66 in the commit, and that's where the comments are. Comments within 6 lines count as near. If none are near, linelore still shows the closest comments on the file but labels them `elsewhere in this file`, so a comment about a different function doesn't pass for an explanation of this line.

### What that costs

For a commit with one PR, linelore makes three API calls (`commits/{sha}/pulls`, `graphql`, `pulls/{n}/comments`). Timing both examples above on my machine with a token took about one second each. Authentication comes from `LINELORE_TOKEN`, `GH_TOKEN` or `GITHUB_TOKEN`, or from `gh auth token` if the GitHub CLI is logged in.

Without any token it still works on public repos, minus the GraphQL step, since GraphQL requires auth. The closing issue then shows up as a plain mention:

```console
$ linelore src/requests/adapters.py:420     # no token, no gh
...
  PR #6716  Allow for overriding of specific pool key params  (@sigmavirus24, merged 2024-05-24)
          https://github.com/psf/requests/pull/6716
          “This re-enables the use case of providing a custom SSLContext via a Transport Adapter as broken in #6655 and reported in #6715 Closes #6715”
  mentions  psf/requests#6655, psf/requests#6715
```

## Offline mode

`--offline` skips the network and shows only the local half of the chain. That's useful on a plane, on a private mirror without API access, or when you only want the commit:

```console
$ linelore src/requests/adapters.py:80 --offline
src/requests/adapters.py:80  DEFAULT_POOLSIZE = 10
  commit  88d4143018  2012-12-15  Kenneth Reitz
          base adapter
  note    offline: showing local commit only
```

Online, that same line gives `note  no pull request found for this commit (pushed directly?)`. It dates from 2012, when requests' history wasn't going through PRs.

## JSON for editors and scripts

`--json` prints everything the terminal view shows plus raw fields: the full sha, `orig_line`, the author's email and timezone, issue bodies, review comment URLs, and a `near` flag per review comment. Trimmed:

```json
{
  "repo": "psf/requests",
  "blame": {
    "sha": "c0813a2d910ea6b4f8438b91d315b8d181302356",
    "line": 75,
    "orig_line": 66,
    "summary": "Use TLS settings in selecting connection pool"
  },
  "pulls": [
    {
      "number": 6655,
      "issues": [],
      "mentions": [],
      "review_comments": [
        { "author": "nateprewitt", "line": 66, "near": true },
        { "author": "sigmavirus24", "line": 66, "near": true }
      ]
    }
  ],
  "notes": []
}
```

That's enough to put linelore behind an editor keybinding or a script:

```console
$ linelore src/requests/adapters.py:420 --json | jq -r '.pulls[] | "\(.url)", (.issues[] | "  fixes \(.url)")'
https://github.com/psf/requests/pull/6716
  fixes https://github.com/psf/requests/issues/6715
```

The schema isn't frozen yet. It becomes stable at v1.0.

## Limits

Some honest limits from trying it on real repositories:

- **Ranges.** `file:10-30` blames a range, deduplicates commits, and follows moves/renames (`-C -M`). Added in v0.2.
- **Moves and renames.** Blame runs with `-C -M` so lore follows code across renames and copies (v0.2).
- **Squash merges of big PRs.** The PR is found correctly, but its body may describe twenty changes, and the line you care about is one of them.
- **`closingIssuesReferences` isn't always populated.** On `requests/adapters.py:258 --rev v2.31.0`, PR #4371 (2017) says "Resolves #4369", but GitHub returns no closing references for it. linelore still shows #4369 under mentions.
- **Review comments are matched by line distance.** That's a heuristic. Comments on a later force-pushed revision can sit at different coordinates, and outdated comments have no line at all. Those are labelled `elsewhere in this file` rather than dropped. Only the first 100 review comments of a PR are read.
- **Forges.** This post walks through GitHub. Since v0.3 linelore also works on GitLab (merge requests, `closes_issues`, diff notes) and Gitea/Forgejo including Codeberg; see [Forges](../forges.md). On gitlab.com, review comments need a `GITLAB_TOKEN`.
- **It can't recover reasoning that was never written down.** If the PR body is empty and nobody reviewed it, linelore will show you that, too.

## Roadmap

- **v0.2 (done)**: line ranges, follow moves/renames, cache API responses per sha.
- **v0.3 (done)**: GitLab and Gitea/Forgejo backends; `--open` to launch the PR in a browser.
- **v0.4 (done)**: editor snippets (Neovim, VS Code task, Helix, Emacs) on top of `--json`, and an optional, clearly labelled `--summarize` that pipes the collected facts to an LLM command you supply.
- **v1.0**: stable JSON schema, PyPI and Homebrew.

## Try it

```bash
pipx install git+https://github.com/Blackman99/linelore
cd any-github-clone
linelore path/to/file.py:42
```

Issues and ideas are welcome at [Blackman99/linelore](https://github.com/Blackman99/linelore/issues). The most useful reports are real lines where linelore found the wrong PR or missed the discussion that mattered.
