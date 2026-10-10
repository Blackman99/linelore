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
    """Parse `git blame --porcelain` output for a single line."""
    lines = text.splitlines()
    if not lines:
        raise GitError("empty blame output")
    head = lines[0].split()
    info = {"sha": head[0], "orig_line": int(head[1]), "line": int(head[2])}
    for ln in lines[1:]:
        if ln.startswith("\t"):
            info["content"] = ln[1:]
            break
        key, _, val = ln.partition(" ")
        if key in ("author", "author-mail", "author-time", "author-tz", "summary", "filename", "previous"):
            info[key.replace("-", "_")] = val
    if "author_time" in info:
        info["author_time"] = int(info["author_time"])
    info["uncommitted"] = set(info["sha"]) == {"0"}
    return info


def blame_line(path, line, rev=None, cwd=None, ignore_revs_file=None):
    args = ["blame", "--porcelain", "-w", "-L", "%d,%d" % (line, line)]
    if ignore_revs_file:
        args += ["--ignore-revs-file", ignore_revs_file]
    if rev:
        args.append(rev)
    args += ["--", path]
    return parse_porcelain(run_git(args, cwd=cwd))


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
