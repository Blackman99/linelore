"""linelore: the story behind a line of code."""
import argparse
import os
import re
import sys

from . import __version__
from .gitops import GitError, blame_lines, dedupe_blames, origin_repo, repo_root
from .github import GitHub, GitHubError, find_token
from .lore import build_lore, build_range_lore
from .render import to_json, to_text

DEMO = {
    "repo": "example/shop", "path": "src/cart.py",
    "blame": {"sha": "3f9c2a71be0d4c55", "line": 42, "orig_line": 40, "author": "Mei Chen",
              "author_time": 1715000000, "summary": "Round totals per line before summing",
              "content": "total += round(item.price * item.qty, 2)"},
    "pulls": [{"number": 812, "title": "Fix cent drift in cart totals", "url": "https://github.com/example/shop/pull/812",
               "author": "meichen", "merged_at": "2024-05-07T09:12:00Z", "state": "closed",
               "body": "Summing floats then rounding drifted by 1c on carts with >30 items; finance flagged it.",
               "issues": [{"number": 790, "title": "Invoice total off by one cent", "url": "https://github.com/example/shop/issues/790",
                           "state": "CLOSED", "body": ""}],
               "mentions": ["example/shop#655"],
               "review_comments": [{"author": "ops-lead", "url": "", "line": 42,
                                    "body": "Use Decimal later; this is the minimal fix for the invoice bug."}]}],
    "notes": [],
}


def parse_target(s):
    """Parse FILE:LINE or FILE:START-END. Returns (path, start, end)."""
    path, sep, rest = s.rpartition(":")
    if not sep or not rest:
        raise argparse.ArgumentTypeError("expected FILE:LINE or FILE:START-END, e.g. src/app.py:42 or src/app.py:10-30")
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", rest)
    if not m:
        raise argparse.ArgumentTypeError("expected FILE:LINE or FILE:START-END, e.g. src/app.py:42 or src/app.py:10-30")
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) is not None else start
    if start < 1 or end < start:
        raise argparse.ArgumentTypeError("invalid line range %s" % rest)
    return path, start, end


def main(argv=None):
    ap = argparse.ArgumentParser(prog="linelore", description="Show the pull request, linked issues and review comments behind a line of code.")
    ap.add_argument("target", nargs="?", help="FILE:LINE or FILE:START-END (or 'demo')")
    ap.add_argument("--rev", help="blame at this revision (default: working tree)")
    ap.add_argument("--repo", help="OWNER/REPO on GitHub (default: from the origin remote)")
    ap.add_argument("--remote", default="origin", help="git remote to read the GitHub repo from")
    ap.add_argument("--ignore-revs-file", help="skip formatting commits (default: .git-blame-ignore-revs if present)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--offline", action="store_true", help="local git only, no GitHub calls")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--api", default=os.environ.get("LINELORE_API", "https://api.github.com"), help="GitHub API base (GHES)")
    ap.add_argument("--version", action="version", version="linelore " + __version__)
    a = ap.parse_args(argv)
    color = sys.stdout.isatty() and not a.no_color and not os.environ.get("NO_COLOR")
    if not a.target:
        ap.print_usage(sys.stderr)
        return 2
    if a.target == "demo":
        print(to_json(DEMO) if a.json else to_text(DEMO, color))
        return 0
    try:
        path, start, end = parse_target(a.target)
    except argparse.ArgumentTypeError as e:
        ap.error(str(e))
    cwd = os.path.dirname(os.path.abspath(path)) or "."
    while not os.path.isdir(cwd) and os.path.dirname(cwd) != cwd:
        cwd = os.path.dirname(cwd)  # with --rev the file's directory may no longer exist
    try:
        root = repo_root(cwd)
        rel = os.path.relpath(os.path.abspath(path), root)
        irf = a.ignore_revs_file
        if irf is None and os.path.exists(os.path.join(root, ".git-blame-ignore-revs")):
            irf = os.path.join(root, ".git-blame-ignore-revs")
        blames = blame_lines(rel, start, end, a.rev, cwd=root, ignore_revs_file=irf)
    except GitError as e:
        print("linelore: " + str(e), file=sys.stderr)
        return 1
    owner = repo = None
    if a.repo:
        owner, _, repo = a.repo.partition("/")
    else:
        r = origin_repo(root, a.remote)
        if r:
            _, owner, repo = r
    gh = None if a.offline else GitHub(find_token(), api=a.api)
    try:
        if start == end:
            lore = build_lore(blames[0], owner, repo, gh, rel)
        else:
            groups = dedupe_blames(blames)
            lore = build_range_lore(groups, owner, repo, gh, rel, start, end)
    except GitHubError as e:
        print("linelore: " + str(e), file=sys.stderr)
        if start == end:
            lore = build_lore(blames[0], owner, repo, None, rel)
        else:
            groups = dedupe_blames(blames)
            lore = build_range_lore(groups, owner, repo, None, rel, start, end)
        lore["notes"].append("GitHub lookup failed: %s" % e)
        print(to_json(lore) if a.json else to_text(lore, color))
        return 3
    print(to_json(lore) if a.json else to_text(lore, color))
    return 0


if __name__ == "__main__":
    sys.exit(main())
