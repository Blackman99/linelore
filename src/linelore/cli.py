"""linelore: the story behind a line of code."""
import argparse
import os
import re
import shutil
import sys
import webbrowser

from . import __version__
from .forge import ForgeError, UnknownForge, change_noun, make_forge, resolve_forge
from .gitops import GitError, blame_lines, dedupe_blames, merge_commit_for, origin_repo, repo_root
from .lore import build_lore, build_range_lore
from .render import to_json, to_text

DEMO = {
    "forge": "github", "repo": "example/shop", "path": "src/cart.py",
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


def _primary_change(lore):
    """The PR/MR --open should launch: the only one, else the most recently merged."""
    pulls = []
    for block in lore.get("commits") or [lore]:
        pulls.extend(p for p in block.get("pulls") or [] if p.get("url"))
    if not pulls:
        return None
    merged = [p for p in pulls if p.get("merged_at")]
    return max(merged, key=lambda p: p["merged_at"]) if merged else pulls[0]


def _headless():
    if os.environ.get("BROWSER"):
        return False
    if sys.platform.startswith(("win", "cygwin", "darwin")):
        return False
    return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def open_in_browser(url):
    """True if a browser took the URL. Never launches a console browser on a headless box."""
    if _headless():
        return False
    try:
        return bool(webbrowser.open(url, new=2))
    except webbrowser.Error:
        return False


def do_open(lore, spec, offline=False):
    """--open: launch the primary PR/MR (or the commit page when there is none)."""
    def say(msg):
        print("linelore: " + msg, file=sys.stderr)
    noun = change_noun(lore.get("forge"))
    pr = _primary_change(lore)
    if pr:
        what, url = "%s %s%d" % (noun[0], noun[1], pr["number"]), pr["url"]
    else:
        b = lore.get("blame") or {}
        if not b or b.get("uncommitted"):
            say("nothing to open: the line is not committed yet")
            return
        if spec is None or not lore.get("repo"):
            say("nothing to open: no forge remote for this repo")
            return
        what, url = "commit %s" % b["sha"][:10], spec.commit_url(lore["repo"], b["sha"])
        if not offline:
            say("no %s for this line, so opening the commit instead" % noun[2])
    if open_in_browser(url):
        say("opened %s in your browser: %s" % (what, url))
    else:
        say("no browser to open here; %s is at %s" % (what, url))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="linelore",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Show the pull request (or merge request), linked issues and review comments behind a line of code.\n"
                    "Works with GitHub, GitLab and Gitea/Forgejo (Codeberg); the forge is read from the remote URL.",
        epilog="examples:\n"
               "  linelore src/app.py:42              the story behind line 42\n"
               "  linelore src/app.py:10-30 --open    a range, then open the newest PR/MR in the browser\n"
               "  linelore lib/x.rb:7 --forge gitlab --api https://git.corp.example/api/v4\n"
               "\n"
               "tokens (all optional on public repos):\n"
               "  GitHub  GH_TOKEN, GITHUB_TOKEN, LINELORE_TOKEN or your `gh` login\n"
               "  GitLab  GITLAB_TOKEN (gitlab.com only shows review comments to signed-in users)\n"
               "  Gitea   GITEA_TOKEN or FORGEJO_TOKEN\n"
               "\n"
               "docs: https://blackman99.github.io/linelore/docs/")
    ap.add_argument("target", nargs="?", help="FILE:LINE or FILE:START-END (or 'demo')")
    ap.add_argument("--rev", metavar="REV", help="blame at this revision (default: working tree)")
    ap.add_argument("--repo", metavar="OWNER/REPO", help="OWNER/REPO on the forge, GROUP/SUBGROUP/PROJECT on GitLab (default: from the remote)")
    ap.add_argument("--remote", default="origin", metavar="NAME", help="git remote to read the forge and repo from (default: origin)")
    ap.add_argument("--forge", choices=["github", "gitlab", "gitea", "forgejo"],
                    help="which forge hosts the repo (default: detected from the remote URL)")
    ap.add_argument("--api", default=None, metavar="URL",
                    help="API base for self-hosted forges, e.g. https://ghe.example.com/api/v3, "
                         "https://gitlab.example.com/api/v4, https://git.example.com/api/v1")
    ap.add_argument("--ignore-revs-file", metavar="PATH", help="skip formatting commits (default: .git-blame-ignore-revs if present)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--open", action="store_true", help="also open the PR/MR in your browser (the newest one for a range)")
    ap.add_argument("--offline", action="store_true", help="local git only, no forge API calls")
    ap.add_argument("--no-color", action="store_true", help="plain text (also when NO_COLOR is set or output is piped)")
    ap.add_argument("--version", action="version", version="linelore " + __version__)
    a = ap.parse_args(argv)
    color = sys.stdout.isatty() and not a.no_color and not os.environ.get("NO_COLOR")
    if not a.target:
        ap.print_usage(sys.stderr)
        return 2
    if a.target == "demo":
        print(to_json(DEMO) if a.json else to_text(DEMO, color))
        if a.open:
            sys.stdout.flush()
            print("linelore: demo data is made up, so there is nothing to open", file=sys.stderr)
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

    host = owner = repo = None
    r = origin_repo(root, a.remote)
    if r:
        host, owner, repo = r
    if a.repo:
        owner, _, repo = a.repo.strip("/").partition("/")
        if not repo:
            ap.error("--repo expects OWNER/REPO, e.g. psf/requests or gitlab-org/cli")
    spec, local_note = None, None
    if owner:
        try:
            spec = resolve_forge(host, a.forge, a.api, os.environ.get("LINELORE_API"))
        except UnknownForge as e:
            local_note = str(e)
    else:
        local_note = ("no forge remote to read the repo from (%s); showing local commit only. "
                      "Pass --repo OWNER/REPO to look it up" % a.remote)
    if a.offline:
        local_note = "offline: showing local commit only"
    forge_name = spec.name if spec else ("gitea" if a.forge == "forgejo" else a.forge)

    def build(gh, note):
        merge_lookup = (lambda sha: merge_commit_for(sha, a.rev, cwd=root))
        if start == end:
            return build_lore(blames[0], owner, repo, gh, rel, forge=forge_name, merge_lookup=merge_lookup,
                              local_note=note)
        return build_range_lore(dedupe_blames(blames), owner, repo, gh, rel, start, end, forge=forge_name,
                                merge_lookup=merge_lookup, local_note=note)

    gh = None if (a.offline or spec is None) else make_forge(spec)
    code = 0
    try:
        lore = build(gh, local_note)
    except ForgeError as e:
        lore = build(None, "")
        lore["notes"].append("lookup failed: %s" % e)
        if a.json:
            print("linelore: lookup failed: %s" % e, file=sys.stderr)
        code = 3
    width = shutil.get_terminal_size((100, 24)).columns if sys.stdout.isatty() else None
    print(to_json(lore) if a.json else to_text(lore, color, width=width))
    if a.open:
        sys.stdout.flush()  # the lore first, then what we opened
        do_open(lore, spec, offline=a.offline or gh is None)
    return code


if __name__ == "__main__":
    sys.exit(main())
