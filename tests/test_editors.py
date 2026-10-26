"""The editor plugins in editors/ read `linelore --json`.

1. Pin the JSON fields they read, on real output: canned demo, recorded
   GitLab and Codeberg responses, a GitHub lore with a promoted issue and a far
   review comment, a range that repeats a PR, a real git repo offline (line,
   range, uncommitted), and a model summary from a fake command.
2. Feed the same JSON to the Neovim and Emacs plugins headless (skipped when
   the editor isn't installed; CI's `editors` job installs both) and check
   what they show and which URLs become links, then run them against the real
   CLI in a scratch repo.
3. Syntax-check the VS Code and Helix snippets.
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from linelore.lore import build_lore, build_range_lore
from test_forges import GL_SHA, GT_SHA, Router, blame, gitea_routes, gitlab_routes
from linelore.gitea import Gitea
from linelore.gitlab import GitLab


def needs(tool):
    """Skip when an editor is missing, except in CI's editors job, where that is a failure."""
    if shutil.which(tool):
        return lambda f: f
    if os.environ.get("LINELORE_EDITORS_REQUIRED"):
        return lambda f: (lambda *a, **k: pytest.fail("%s is not installed" % tool))
    return pytest.mark.skip(reason="%s not installed" % tool)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDITORS = os.path.join(ROOT, "editors")

# Every field the plugins read. A rename here breaks editors/: update both.
# (type, required) - optional fields may be absent (older output, demo, offline).
STR, INT, BOOL, LIST, DICT, NONE = str, int, bool, list, dict, type(None)
TOP = {"forge": ((STR, NONE), True), "path": (STR, True), "notes": (LIST, True)}
SINGLE = {"blame": (DICT, True), "pulls": (LIST, True)}
RANGE = {"range": (DICT, True), "commits": (LIST, True)}
BLAME = {"sha": (STR, True), "line": (INT, True), "author": (STR, True), "author_time": (INT, True),
         "summary": (STR, True), "content": (STR, True), "uncommitted": (BOOL, False)}
COMMIT = {"blame": (DICT, True), "lines": (LIST, True), "pulls": (LIST, True), "notes": (LIST, True)}
PULL = {"number": (INT, True), "title": ((STR, NONE), True), "url": ((STR, NONE), True),
        "author": ((STR, NONE), True), "merged_at": ((STR, NONE), True), "state": ((STR, NONE), True),
        "body": ((STR, NONE), True), "issues": (LIST, True), "mentions": (LIST, True),
        "review_comments": (LIST, True)}
ISSUE = {"number": (INT, True), "title": ((STR, NONE), True), "url": ((STR, NONE), True),
         "state": ((STR, NONE), True), "promoted": (BOOL, False)}
REVIEW = {"author": ((STR, NONE), True), "line": ((INT, NONE), True), "body": ((STR, NONE), True),
          "near": (BOOL, False)}
SUMMARY = {"by": (STR, True), "text": ((STR, NONE), True), "error": ((STR, NONE), True), "disclaimer": (STR, True)}


def check_fields(obj, spec, where):
    assert isinstance(obj, dict), where
    for key, (types, required) in spec.items():
        if key not in obj:
            assert not required, "%s: missing %r" % (where, key)
            continue
        if not isinstance(types, tuple):
            types = (types,)
        val = obj[key]
        ok = isinstance(val, types) and not (bool in [type(val)] and bool not in types)
        assert ok, "%s.%s: %r is not %s" % (where, key, val, types)


def check_pulls(pulls, where):
    for i, pr in enumerate(pulls):
        w = "%s.pulls[%d]" % (where, i)
        check_fields(pr, PULL, w)
        for iss in pr["issues"]:
            check_fields(iss, ISSUE, w + ".issues")
        assert all(isinstance(m, str) for m in pr["mentions"]), w + ".mentions are strings"
        for rc in pr["review_comments"]:
            check_fields(rc, REVIEW, w + ".review_comments")


def check_lore(lore, name):
    check_fields(lore, TOP, name)
    if "range" in lore:
        check_fields(lore, RANGE, name)
        assert set(lore["range"]) >= {"start", "end"}
        for i, c in enumerate(lore["commits"]):
            check_fields(c, COMMIT, "%s.commits[%d]" % (name, i))
            check_fields(c["blame"], BLAME, "%s.commits[%d].blame" % (name, i))
            assert all(isinstance(n, int) for n in c["lines"])
            check_pulls(c["pulls"], "%s.commits[%d]" % (name, i))
    else:
        check_fields(lore, SINGLE, name)
        check_fields(lore["blame"], BLAME, name + ".blame")
        check_pulls(lore["pulls"], name)
    if "model_summary" in lore:
        check_fields(lore["model_summary"], SUMMARY, name + ".model_summary")
    assert all(isinstance(n, str) for n in lore["notes"])


# ------------------------------------------------------------------ fixtures

def _git(cwd, *a):
    subprocess.run(["git", "-c", "user.name=Mei Chen", "-c", "user.email=m@e", *a], cwd=cwd, check=True,
                   capture_output=True)


def run_json(args, cwd=None, env=None):
    p = subprocess.run([sys.executable, "-m", "linelore", "--json", "--no-color", *args], cwd=cwd,
                       capture_output=True, text=True, encoding="utf-8", env=env)
    assert p.returncode in (0, 3, 4), p.stderr
    return json.loads(p.stdout)


class FakeGH:
    name = "github"

    def commit_pulls(self, o, r, sha):
        return [{"number": 4134, "title": "Raise exceptions in utils.set_environ",
                 "html_url": "https://github.com/psf/requests/pull/4134", "user": {"login": "mlcrazy"},
                 "merged_at": "2017-06-09T13:11:51Z", "state": "closed",
                 "body": "fixes #4127. Related to #4122"}]

    def closing_issues(self, o, r, n):
        return []  # forces the "Fixes #N in the body" promotion path

    def issue(self, o, r, n):
        return None

    def pull_review_comments(self, o, r, n):
        return [{"path": "utils.py", "line": 621, "original_line": 621, "user": {"login": "nateprewitt"},
                 "html_url": "https://github.com/psf/requests/pull/4134#discussion_r120", "body": "adding value_changed?"},
                {"path": "utils.py", "line": 30, "original_line": 30, "user": {"login": "Lukasa"},
                 "html_url": "https://github.com/psf/requests/pull/4134#discussion_r121", "body": "We don't need this newline."}]


@pytest.fixture(scope="module")
def scratch(tmp_path_factory):
    d = tmp_path_factory.mktemp("repo")
    _git(d, "init", "-q")
    f = d / "cart.py"
    f.write_text("def total(items):\n    t = 0\n    for i in items:\n        t += i\n    return t\n")
    _git(d, "add", ".")
    _git(d, "commit", "-qm", "Add cart total")
    f.write_text("def total(items):\n    t = 0\n    for i in items:\n        t += round(i, 2)\n    return t\n")
    _git(d, "commit", "-qam", "Round each line before summing")
    with open(f, "a") as fh:
        fh.write("# not committed\n")
    return d


@pytest.fixture(scope="module")
def cases(scratch, tmp_path_factory):
    """{name: lore} plus what each editor must show for it."""
    c = []

    def add(name, lore, want, links=(), absent=()):
        c.append({"name": name, "lore": lore, "want": list(want), "links": list(links), "absent": list(absent)})

    demo = run_json(["demo"])
    add("demo", demo, ["src/cart.py:42", "total += round(item.price * item.qty, 2)", "3f9c2a71be",
                       "2024-05-06", "PR #812", "Fix cent drift in cart totals", "@meichen", "merged 2024-05-07",
                       "fixes", "#790", "[closed]", "example/shop#655", "@ops-lead (line 42)", "minimal fix"],
        links=["https://github.com/example/shop/pull/812", "https://github.com/example/shop/issues/790"],
        absent=["Summary"])

    gl = GitLab("t", api="https://gitlab.com/api/v4", opener=Router(gitlab_routes()), cache_dir=False)
    add("gitlab", build_lore(blame(GL_SHA, 290, 313), "gitlab-org", "cli", gl, "internal/commands/packages/download/download.go"),
        ["MR !4112", "fixes", "#8615", "@jhebden (line 313)"],
        links=["https://gitlab.com/gitlab-org/cli/-/merge_requests/4112"], absent=["PR #"])

    gt = Gitea("t", api="https://codeberg.org/api/v1", opener=Router(gitea_routes()), cache_dir=False)
    add("codeberg", build_lore(blame(GT_SHA, 5, 5, filename=".gitignore"), "dnkl", "foot", gt, ".gitignore"),
        ["PR #2463", "#2462", "@cismonx"], links=["https://codeberg.org/dnkl/foot/pulls/2463",
                                                  "https://codeberg.org/dnkl/foot/issues/2462"])

    b = blame("1d7fd6c8b3" + "0" * 30, 795, 621, filename="utils.py")
    gh_lore = build_lore(b, "psf", "requests", FakeGH(), "utils.py")
    add("github-promoted", gh_lore, ["PR #4134", "#4127", "[mentioned]", "@nateprewitt (line 621)"],
        links=["https://github.com/psf/requests/pull/4134", "https://github.com/psf/requests/issues/4127"])

    rows = [dict(blame("a" * 40, 10, 10, filename="utils.py"), content="first"),
            dict(blame("b" * 40, 12, 12, filename="utils.py"), content="second")]
    groups = [{"blame": rows[0], "lines": [10, 11, 13]}, {"blame": rows[1], "lines": [12]}]
    rng = build_range_lore(groups, "psf", "requests", FakeGH(), "utils.py", 10, 13)
    add("range-same-pr", rng, ["utils.py:10–13", "2 unique commits", "lines 10–11, 13", "lines 12",
                               "same PR as above", "elsewhere in this file, line 30 at review time"],
        absent=["note    2 unique commits"])

    path = str(scratch / "cart.py")
    add("offline-line", run_json([path + ":4", "--offline"]),
        ["cart.py:4", "t += round(i, 2)", "Round each line before summing", "Mei Chen", "offline"])
    add("offline-range", run_json([path + ":1-5", "--offline"]),
        ["cart.py:1–5", "2 unique commits", "lines 1–3, 5", "lines 4", "Add cart total"])
    add("uncommitted", run_json([path + ":6", "--offline"]), ["cart.py:6", "not committed yet"],
        absent=["0000000000"])

    script = tmp_path_factory.mktemp("llm") / "fake_llm.py"
    script.write_text("import sys\nsys.stdin.read()\nprint('Rounded per line (#812), as @ops-lead asked.')\n")
    env = dict(os.environ)
    env["LINELORE_SUMMARIZE_CMD"] = "%s %s" % (sys.executable, script) if os.name != "nt" else \
        '"%s" "%s"' % (sys.executable, script)
    summary = run_json(["demo", "--summarize"], env=env)
    add("summary", summary, ["PR #812", "Summary (generated by", "may be wrong; not checked by linelore",
                             "Rounded per line (#812)"])
    env["LINELORE_SUMMARIZE_CMD"] = "linelore-no-such-model"
    failed = run_json(["demo", "--summarize"], env=env)
    add("summary-failed", failed, ["PR #812", "No summary:", "`linelore-no-such-model`"], absent=["Summary (generated"])
    return c


def test_json_fields_the_editors_read(cases):
    assert len(cases) == 10
    for case in cases:
        check_lore(case["lore"], case["name"])
    by = {c["name"]: c["lore"] for c in cases}
    assert by["uncommitted"]["blame"]["uncommitted"] is True
    assert by["github-promoted"]["pulls"][0]["issues"][0]["promoted"] is True
    assert [rc["near"] for rc in by["github-promoted"]["pulls"][0]["review_comments"]] == [True]
    assert {rc["near"] for rc in by["range-same-pr"]["commits"][0]["pulls"][0]["review_comments"]} == {False}
    assert by["summary"]["model_summary"]["text"] and by["summary"]["model_summary"]["error"] is None
    assert by["summary-failed"]["model_summary"]["text"] is None and by["summary-failed"]["model_summary"]["error"]
    # the summary never leaks into the facts
    facts = dict(by["summary"])
    facts.pop("model_summary")
    assert facts == by["demo"]


# ------------------------------------------------------------------- editors

@pytest.fixture(scope="module")
def cases_file(cases, scratch, tmp_path_factory):
    f = tmp_path_factory.mktemp("cases") / "cases.json"
    live = {"file": str(scratch / "cart.py"), "cmd": [sys.executable, "-m", "linelore"], "args": ["--offline"],
            "steps": [
                {"ex": "4Linelore", "line": 4, "want": ["cart.py:4", "Round each line before summing", "offline",
                                                        "commit"]},
                {"ex": "1,5Linelore", "line": 1, "to": 5, "want": ["cart.py:1–5", "2 unique commits", "lines 4"]},
            ]}
    f.write_text(json.dumps({"render": cases, "live": live}), encoding="utf-8")
    return f


@needs("nvim")
def test_neovim_plugin(cases_file):
    p = subprocess.run(["nvim", "--headless", "-u", "NONE", "-i", "NONE", "--cmd",
                        "set rtp^=" + os.path.join(EDITORS, "nvim"), "-l",
                        os.path.join(EDITORS, "nvim", "test", "smoke.lua"), str(cases_file)],
                       capture_output=True, text=True, timeout=120)
    print(p.stdout, p.stderr)
    assert p.returncode == 0, p.stderr
    assert "all nvim checks passed" in p.stdout + p.stderr


@needs("emacs")
def test_emacs_package(cases_file):
    env = dict(os.environ, LINELORE_EDITOR_CASES=str(cases_file))
    el = os.path.join(EDITORS, "emacs")
    compile_ = subprocess.run(["emacs", "--batch", "-Q", "--eval", "(setq byte-compile-error-on-warn t)",
                               "--eval", "(setq byte-compile-dest-file-function (lambda (_) (make-temp-file \"ll\" nil \".elc\")))",
                               "-f", "batch-byte-compile", os.path.join(el, "linelore.el")],
                              capture_output=True, text=True, timeout=60)
    assert compile_.returncode == 0, compile_.stderr
    p = subprocess.run(["emacs", "--batch", "-Q", "-L", el, "-l", os.path.join(el, "test", "linelore-test.el"),
                        "-f", "ert-run-tests-batch-and-exit"], capture_output=True, text=True, env=env, timeout=120)
    print(p.stdout, p.stderr)
    assert p.returncode == 0, p.stderr
    assert re.search(r"Ran 3 tests, 3 results as expected", p.stderr), p.stderr


# -------------------------------------------------------- VS Code and Helix

def jsonc(path):
    """VS Code files allow // comments and trailing commas."""
    text = open(path, encoding="utf-8").read()
    text = re.sub(r'("(?:\\.|[^"\\])*")|//[^\n]*', lambda m: m.group(1) or "", text)
    text = re.sub(r",(\s*[\]}])", r"\1", text)
    return json.loads(text)


VSCODE_VARS = {"file", "fileDirname", "relativeFile", "lineNumber", "workspaceFolder", "input:lineRange"}


def test_vscode_snippets():
    tasks = jsonc(os.path.join(EDITORS, "vscode", "tasks.json"))
    assert tasks["version"] == "2.0.0"
    labels = {t["label"] for t in tasks["tasks"]}
    for t in tasks["tasks"]:
        assert t["type"] == "process" and t["command"] == "linelore", t
        used = set(re.findall(r"\$\{([^}]+)\}", json.dumps(t)))
        assert used <= VSCODE_VARS, used - VSCODE_VARS
        assert "--json" not in t["args"]  # the terminal shows text; the URLs in it are clickable
    assert tasks["inputs"][0]["id"] == "lineRange"
    keys = jsonc(os.path.join(EDITORS, "vscode", "keybindings.json"))
    for k in keys:
        assert k["command"] == "workbench.action.tasks.runTask" and k["args"] in labels, k


def test_helix_snippet():
    try:
        import tomllib
    except ImportError:  # Python < 3.11
        pytest.skip("tomllib needs Python 3.11+")
    path = os.path.join(EDITORS, "helix", "config.toml")
    with open(path, "rb") as f:
        conf = tomllib.load(f)
    binds = [v for mode in conf["keys"].values() for v in mode.get("space", {}).get("l", {}).values()]
    assert binds and all(isinstance(v, str) and v.startswith(":sh linelore ") for v in binds)
    for v in binds:
        for var in re.findall(r"%\{([^}]+)\}", v):
            assert var in {"buffer_name", "cursor_line", "selection_line_start", "selection_line_end"}, var


@needs("hx")
def test_helix_accepts_the_config(tmp_path):
    cfg = tmp_path / "helix"
    cfg.mkdir()
    shutil.copy(os.path.join(EDITORS, "helix", "config.toml"), cfg / "config.toml")
    p = subprocess.run(["hx", "--config", str(cfg / "config.toml"), "--health", "clipboard"],
                       capture_output=True, text=True, timeout=30)
    assert p.returncode == 0 and "malformed" not in p.stdout + p.stderr, p.stdout + p.stderr
