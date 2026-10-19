"""Local git helpers (blame, remote parsing)."""
import re
import subprocess


class GitError(RuntimeError):
    pass


def run_git(args, cwd=None):
    p = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise GitError(p.stderr.strip() or "git %s failed" % " ".join(args))
    return p.stdout


def parse_porcelain(text):
    """Parse `git blame --porcelain` for one or more lines.

    Returns a list of per-line blame dicts. Consecutive lines that share a
    commit reuse the commit metadata from the first header for that sha
    (porcelain omits author/summary on later occurrences).
    """
    lines = text.splitlines()
    if not lines:
        raise GitError("empty blame output")
    by_sha = {}
    out = []
    i = 0
    n = len(lines)
    while i < n:
        head = lines[i].split()
        if len(head) < 3 or not re.fullmatch(r"[0-9a-f]{4,40}", head[0]):
            raise GitError("unexpected blame header: %s" % lines[i][:80])
        sha, orig_line, final_line = head[0], int(head[1]), int(head[2])
        i += 1
        meta = {}
        content = None
        while i < n:
            ln = lines[i]
            if ln.startswith("\t"):
                content = ln[1:]
                i += 1
                break
            if re.match(r"^[0-9a-f]{4,40} ", ln):
                break  # next header without a content line (shouldn't happen)
            key, _, val = ln.partition(" ")
            if key in ("author", "author-mail", "author-time", "author-tz",
                       "summary", "filename", "previous"):
                meta[key.replace("-", "_")] = val
            i += 1
        if sha in by_sha:
            info = dict(by_sha[sha])
            info.update(meta)  # keep any newly seen fields; preserve author etc.
        else:
            info = dict(meta)
            by_sha[sha] = info
        entry = dict(by_sha[sha])
        entry["sha"] = sha
        entry["orig_line"] = orig_line
        entry["line"] = final_line
        if "author_time" in entry and not isinstance(entry["author_time"], int):
            entry["author_time"] = int(entry["author_time"])
        entry["content"] = content if content is not None else ""
        entry["uncommitted"] = set(sha) == {"0"}
        # refresh stored metadata (first sighting wins for author/summary)
        for k, v in meta.items():
            by_sha[sha].setdefault(k, v)
        if "author_time" in by_sha[sha] and not isinstance(by_sha[sha]["author_time"], int):
            by_sha[sha]["author_time"] = int(by_sha[sha]["author_time"])
        out.append(entry)
    if not out:
        raise GitError("empty blame output")
    return out


def blame_lines(path, start, end, rev=None, cwd=None, ignore_revs_file=None):
    """Blame lines start..end (inclusive). Follows moves/copies via -C -M."""
    if start < 1 or end < start:
        raise GitError("invalid line range %s-%s" % (start, end))
    args = ["blame", "--porcelain", "-w", "-C", "-M", "-L", "%d,%d" % (start, end)]
    if ignore_revs_file:
        args += ["--ignore-revs-file", ignore_revs_file]
    if rev:
        args.append(rev)
    args += ["--", path]
    return parse_porcelain(run_git(args, cwd=cwd))


def blame_line(path, line, rev=None, cwd=None, ignore_revs_file=None):
    """Blame a single line; returns one dict (compat with v0.1)."""
    return blame_lines(path, line, line, rev=rev, cwd=cwd,
                       ignore_revs_file=ignore_revs_file)[0]


def dedupe_blames(blames):
    """Group per-line blames by commit sha, preserving first-appearance order.

    Returns a list of dicts: {blame, lines} where blame is the first line's
    metadata for that sha and lines is the sorted list of final line numbers.
    """
    order = []
    groups = {}
    for b in blames:
        sha = b["sha"]
        if sha not in groups:
            groups[sha] = {"blame": b, "lines": []}
            order.append(sha)
        groups[sha]["lines"].append(b["line"])
    return [groups[sha] for sha in order]


def merge_commit_for(sha, rev=None, cwd=None):
    """The merge commit that brought `sha` into the first-parent history of rev/HEAD.

    Gitea/Forgejo can only map a PR's merge commit to the PR, so for repos that
    merge with merge commits we look the merge up locally. Returns None when
    `sha` is on the first-parent line itself (direct push, squash, rebase,
    fast-forward), or when git can't tell."""
    head = rev or "HEAD"
    try:
        mainline = run_git(["rev-list", "--first-parent", "--merges", "%s..%s" % (sha, head)], cwd=cwd).split()
        if not mainline:
            return None
        descendants = set(run_git(["rev-list", "--ancestry-path", "--merges", "%s..%s" % (sha, head)], cwd=cwd).split())
        candidates = [c for c in mainline if c in descendants]  # newest first
        if not candidates:
            return None
        merge = candidates[-1]  # the oldest mainline merge that contains sha
        # If sha was already on the mainline before that merge, no merge brought it in.
        p = subprocess.run(["git", "merge-base", "--is-ancestor", sha, merge + "^1"], cwd=cwd,
                           capture_output=True, text=True)
        return None if p.returncode == 0 else merge
    except (GitError, OSError):
        return None


_REMOTE_RES = [
    re.compile(r"^git@([^:]+):(?P<o>[^/]+)/(?P<r>.+?)(?:\.git)?/?$"),
    re.compile(r"^(?:https?|ssh|git)://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(?P<o>[^/]+)/(?P<r>.+?)(?:\.git)?/?$"),
]


def parse_remote(url):
    """Return (host, owner, repo) from a git remote URL, or None."""
    url = url.strip()
    for rx in _REMOTE_RES:
        m = rx.match(url)
        if m:
            return m.group(1), m.group("o"), m.group("r")
    return None


def origin_repo(cwd=None, remote="origin"):
    try:
        url = run_git(["remote", "get-url", remote], cwd=cwd)
    except GitError:
        return None
    return parse_remote(url)


def repo_root(cwd=None):
    return run_git(["rev-parse", "--show-toplevel"], cwd=cwd).strip()
