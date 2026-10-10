import json
import subprocess

import pytest

from linelore import cli
from linelore.gitops import parse_porcelain, parse_remote, blame_line
from linelore.lore import build_lore, issue_refs, excerpt, comments_for

PORC = """3f9c2a71be0d4c55aa00112233445566778899aa 40 42 1
author Mei Chen
author-mail <mei@example.com>
author-time 1715000000
author-tz +0000
summary Round totals
filename src/cart.py
\ttotal += 1
"""


def test_parse_porcelain():
    b = parse_porcelain(PORC)
    assert b["sha"].startswith("3f9c") and b["line"] == 42 and b["orig_line"] == 40
    assert b["author"] == "Mei Chen" and b["content"] == "total += 1" and not b["uncommitted"]


@pytest.mark.parametrize("url,exp", [
    ("git@github.com:psf/requests.git", ("github.com", "psf", "requests")),
    ("https://github.com/psf/requests", ("github.com", "psf", "requests")),
    ("https://token@github.com/a/b.git", ("github.com", "a", "b")),
    ("ssh://git@ghe.corp:2222/team/svc.git", ("ghe.corp", "team", "svc")),
])
def test_parse_remote(url, exp):
    assert parse_remote(url) == exp


def test_parse_remote_bad():
    assert parse_remote("/local/path") is None


def test_issue_refs_and_excerpt():
    assert issue_refs("Fixes #12 and other/x#3, see #12", "o", "r") == [("o/r", 12), ("other/x", 3)]
    assert excerpt("a <!-- hidden --> b\n\nc") == "a b c"
    assert excerpt("x" * 500, 10).endswith("…")


def test_comments_for_prefers_nearby():
    cs = [{"path": "a.py", "line": 100, "body": "far"}, {"path": "a.py", "line": 41, "body": "near"},
          {"path": "b.py", "line": 41, "body": "other"}]
    near, is_near = comments_for(cs, "a.py", 40)
    assert [c["body"] for c in near] == ["near"] and is_near
    allc, is_near = comments_for(cs, "a.py", None)
    assert len(allc) == 2 and not is_near


def test_far_review_comments_are_labelled():
    from linelore.render import to_text
    lore = {"path": "a.py", "blame": {"sha": "abc1234567", "line": 500, "summary": "s"}, "notes": [],
            "pulls": [{"number": 1, "title": "t", "author": "u", "merged_at": "2024-01-01", "url": "x", "body": "",
                       "issues": [], "mentions": [],
                       "review_comments": [{"author": "r", "line": 66, "body": "hm", "near": False}]}]}
    assert "elsewhere in this file, line 66 at review time" in to_text(lore)
    lore["pulls"][0]["review_comments"][0]["line"] = None
    assert "outdated diff" in to_text(lore)


class FakeGH:
    def __init__(self, pulls):
        self.pulls = pulls
    def commit_pulls(self, o, r, sha):
        return self.pulls
    def closing_issues(self, o, r, n):
        return [{"number": 7, "title": "Bug", "url": "u", "state": "CLOSED", "body": "b"}]
    def pull_review_comments(self, o, r, n):
        return [{"path": "src/cart.py", "line": 41, "body": "why not Decimal?", "user": {"login": "rev"}}]


def test_build_lore_full():
    b = parse_porcelain(PORC)
    pr = {"number": 9, "title": "Fix", "html_url": "p", "user": {"login": "m"}, "merged_at": "2024-01-01",
          "state": "closed", "body": "Closes #7, related #3"}
    lore = build_lore(b, "o", "r", FakeGH([pr]), "src/cart.py")
    p = lore["pulls"][0]
    assert p["issues"][0]["number"] == 7 and p["mentions"] == ["o/r#3"]
    assert p["review_comments"][0]["author"] == "rev"


def test_build_lore_no_pr_and_offline():
    b = parse_porcelain(PORC)
    assert "no pull request" in build_lore(b, "o", "r", FakeGH([]), "x")["notes"][0]
    assert build_lore(b, "o", "r", None, "x")["notes"][0].startswith("offline:")
    assert "no GitHub remote" in build_lore(b, None, None, FakeGH([]), "x")["notes"][0]


def _git(cwd, *a):
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@e", *a], cwd=cwd, check=True, capture_output=True)


def test_real_git_repo_offline(tmp_path, capsys):
    _git(tmp_path, "init", "-q")
    (tmp_path / "f.txt").write_text("one\ntwo\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "add f")
    b = blame_line("f.txt", 2, cwd=str(tmp_path))
    assert b["content"] == "two" and b["summary"] == "add f"
    assert cli.main([str(tmp_path / "f.txt") + ":2", "--offline", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["blame"]["summary"] == "add f"


def test_demo_and_bad_target(capsys):
    assert cli.main(["demo", "--no-color"]) == 0
    assert "PR #812" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["nofile"])
