import json
import subprocess

import pytest

from linelore import cli
from linelore.gitops import parse_porcelain, parse_remote, blame_line, blame_lines, dedupe_blames, run_git
from linelore.github import GitHub, resolve_cache_dir
from linelore.lore import build_lore, build_range_lore, issue_refs, closing_refs, excerpt, comments_for
from linelore.render import to_text, _format_lines

PORC = """3f9c2a71be0d4c55aa00112233445566778899aa 40 42 1
author Mei Chen
author-mail <mei@example.com>
author-time 1715000000
author-tz +0000
summary Round totals
filename src/cart.py
\ttotal += 1
"""

PORC_RANGE = """aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 1 10 2
author Ada
author-mail <a@e>
author-time 1715000000
author-tz +0000
summary first
filename f.py
\tone
aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 2 11
\ttwo
bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 3 12 1
author Bob
author-mail <b@e>
author-time 1715000100
author-tz +0000
summary second
filename f.py
\tthree
aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 4 13 1
\tfour
"""


def test_parse_porcelain():
    b = parse_porcelain(PORC)
    assert isinstance(b, list) and len(b) == 1
    b = b[0]
    assert b["sha"].startswith("3f9c") and b["line"] == 42 and b["orig_line"] == 40
    assert b["author"] == "Mei Chen" and b["content"] == "total += 1" and not b["uncommitted"]


def test_parse_porcelain_range_and_dedupe():
    rows = parse_porcelain(PORC_RANGE)
    assert [r["line"] for r in rows] == [10, 11, 12, 13]
    assert rows[0]["author"] == "Ada" and rows[1]["author"] == "Ada"
    assert rows[2]["author"] == "Bob"
    assert rows[3]["author"] == "Ada" and rows[3]["summary"] == "first"
    groups = dedupe_blames(rows)
    assert len(groups) == 2
    assert groups[0]["blame"]["sha"].startswith("aaa") and groups[0]["lines"] == [10, 11, 13]
    assert groups[1]["blame"]["sha"].startswith("bbb") and groups[1]["lines"] == [12]


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


def test_closing_refs():
    assert closing_refs("Fixes #12 and closes other/x#3; see #9", "o", "r") == [("o/r", 12), ("other/x", 3)]
    assert closing_refs("Resolved #7", "o", "r") == [("o/r", 7)]
    assert closing_refs("related to #9", "o", "r") == []


def test_comments_for_prefers_nearby():
    cs = [{"path": "a.py", "line": 100, "body": "far"}, {"path": "a.py", "line": 41, "body": "near"},
          {"path": "b.py", "line": 41, "body": "other"}]
    near, is_near = comments_for(cs, "a.py", 40)
    assert [c["body"] for c in near] == ["near"] and is_near
    allc, is_near = comments_for(cs, "a.py", None)
    assert len(allc) == 2 and not is_near


def test_far_review_comments_are_labelled():
    lore = {"path": "a.py", "blame": {"sha": "abc1234567", "line": 500, "summary": "s"}, "notes": [],
            "pulls": [{"number": 1, "title": "t", "author": "u", "merged_at": "2024-01-01", "url": "x", "body": "",
                       "issues": [], "mentions": [],
                       "review_comments": [{"author": "r", "line": 66, "body": "hm", "near": False}]}]}
    assert "elsewhere in this file, line 66 at review time" in to_text(lore)
    lore["pulls"][0]["review_comments"][0]["line"] = None
    assert "outdated diff" in to_text(lore)


def test_format_lines_and_range_text():
    assert _format_lines([10, 11, 12, 15, 20, 21]) == "10–12, 15, 20–21"
    lore = {
        "path": "f.py",
        "range": {"start": 10, "end": 13},
        "blame": {"sha": "a" * 40, "line": 10, "author": "Ada", "author_time": 1715000000, "summary": "first", "content": "one"},
        "pulls": [],
        "commits": [
            {"blame": {"sha": "a" * 40, "line": 10, "author": "Ada", "author_time": 1715000000, "summary": "first", "content": "one"},
             "lines": [10, 11, 13], "pulls": [], "notes": []},
            {"blame": {"sha": "b" * 40, "line": 12, "author": "Bob", "author_time": 1715000100, "summary": "second", "content": "three"},
             "lines": [12], "pulls": [], "notes": ["offline: showing local commit only"]},
        ],
        "notes": ["2 unique commits in lines 10–13"],
    }
    text = to_text(lore)
    assert "f.py:10–13" in text and "2 unique commits" in text
    assert "lines 10–11, 13" in text and "lines 12" in text


class FakeGH:
    def __init__(self, pulls, issues=None):
        self.pulls = pulls
        self._issues = issues
        self.commit_pulls_calls = 0
    def commit_pulls(self, o, r, sha):
        self.commit_pulls_calls += 1
        return self.pulls
    def closing_issues(self, o, r, n):
        if self._issues is not None:
            return self._issues
        return [{"number": 7, "title": "Bug", "url": "u", "state": "CLOSED", "body": "b"}]
    def pull_review_comments(self, o, r, n):
        return [{"path": "src/cart.py", "line": 41, "body": "why not Decimal?", "user": {"login": "rev"}}]


def test_build_lore_full():
    b = parse_porcelain(PORC)[0]
    pr = {"number": 9, "title": "Fix", "html_url": "p", "user": {"login": "m"}, "merged_at": "2024-01-01",
          "state": "closed", "body": "Closes #7, related #3"}
    lore = build_lore(b, "o", "r", FakeGH([pr]), "src/cart.py")
    p = lore["pulls"][0]
    assert p["issues"][0]["number"] == 7 and p["mentions"] == ["o/r#3"]
    assert p["review_comments"][0]["author"] == "rev"


def test_promote_closes_when_graphql_empty():
    b = parse_porcelain(PORC)[0]
    pr = {"number": 9, "title": "Fix handshake", "html_url": "p", "user": {"login": "m"},
          "merged_at": "2024-01-01", "state": "closed",
          "body": "This re-enables the use case. Closes #6715. Related #6655"}
    lore = build_lore(b, "o", "r", FakeGH([pr], issues=[]), "src/cart.py")
    p = lore["pulls"][0]
    assert len(p["issues"]) == 1 and p["issues"][0]["number"] == 6715
    assert p["issues"][0].get("promoted") is True
    assert p["mentions"] == ["o/r#6655"]


def test_build_lore_no_pr_and_offline():
    b = parse_porcelain(PORC)[0]
    assert "no pull request" in build_lore(b, "o", "r", FakeGH([]), "x")["notes"][0]
    assert build_lore(b, "o", "r", None, "x")["notes"][0].startswith("offline:")
    assert "no GitHub remote" in build_lore(b, None, None, FakeGH([]), "x")["notes"][0]


def test_build_range_lore_dedupes_api():
    rows = parse_porcelain(PORC_RANGE)
    groups = dedupe_blames(rows)
    gh = FakeGH([])
    lore = build_range_lore(groups, "o", "r", gh, "f.py", 10, 13)
    assert lore["range"] == {"start": 10, "end": 13}
    assert len(lore["commits"]) == 2
    assert lore["commits"][0]["lines"] == [10, 11, 13]
    assert gh.commit_pulls_calls == 2  # one per unique sha


def test_parse_target():
    assert cli.parse_target("src/a.py:42") == ("src/a.py", 42, 42)
    assert cli.parse_target("src/a.py:10-30") == ("src/a.py", 10, 30)
    with pytest.raises(Exception):
        cli.parse_target("nofile")
    with pytest.raises(Exception):
        cli.parse_target("f.py:30-10")


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


def test_real_git_range_dedupe(tmp_path, capsys):
    _git(tmp_path, "init", "-q")
    (tmp_path / "f.txt").write_text("a\nb\nc\nd\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "add all")
    (tmp_path / "f.txt").write_text("a\nB\nC\nd\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "change mid")
    rows = blame_lines("f.txt", 1, 4, cwd=str(tmp_path))
    groups = dedupe_blames(rows)
    assert len(groups) == 2
    assert sorted(groups[0]["lines"] + groups[1]["lines"]) == [1, 2, 3, 4]
    assert cli.main([str(tmp_path / "f.txt") + ":1-4", "--offline", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["range"] == {"start": 1, "end": 4}
    assert len(out["commits"]) == 2


def test_blame_passes_c_and_m(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q")
    (tmp_path / "old.txt").write_text("alpha\nbeta\ngamma\ndelta\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "add old")
    _git(tmp_path, "mv", "old.txt", "new.txt")
    _git(tmp_path, "commit", "-qm", "rename")
    seen = []
    real = run_git

    def spy(args, cwd=None):
        seen.append(list(args))
        return real(args, cwd=cwd)

    monkeypatch.setattr("linelore.gitops.run_git", spy)
    b = blame_line("new.txt", 2, cwd=str(tmp_path))
    assert b["summary"] == "add old"
    blame_args = next(a for a in seen if a and a[0] == "blame")
    assert "-C" in blame_args and "-M" in blame_args


def test_demo_and_bad_target(capsys):
    assert cli.main(["demo", "--no-color"]) == 0
    assert "PR #812" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["nofile"])


def test_rev_path_missing_from_worktree(tmp_path, capsys, monkeypatch):
    _git(tmp_path, "init", "-q")
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "f.txt").write_text("one\ntwo\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "add old/f")
    _git(tmp_path, "tag", "v1")
    _git(tmp_path, "rm", "-rq", "old")
    _git(tmp_path, "commit", "-qm", "move away")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["old/f.txt:2", "--rev", "v1", "--offline", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["blame"]["summary"] == "add old/f"


class RecordingOpener:
    """urllib-like opener that records requests and returns canned JSON."""
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(self, req, timeout=20):
        self.calls.append((req.get_method(), req.full_url))
        body = json.dumps(self.payload).encode()

        class Resp:
            def read(self_inner):
                return body
            def __enter__(self_inner):
                return self_inner
            def __exit__(self_inner, *a):
                return False
        return Resp()


def test_api_cache_memory_and_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("LINELORE_CACHE", str(tmp_path / "cache"))
    opener = RecordingOpener([{"number": 1, "title": "t", "html_url": "u", "user": {"login": "x"},
                               "merged_at": None, "state": "open", "body": ""}])
    gh = GitHub(token="t", opener=opener)
    assert gh.cache_dir == str(tmp_path / "cache")
    a = gh.commit_pulls("o", "r", "abc123")
    b = gh.commit_pulls("o", "r", "abc123")
    assert a == b and len(opener.calls) == 1  # memory hit
    # Fresh instance should hit disk, not network
    opener2 = RecordingOpener([{"number": 99}])
    gh2 = GitHub(token="t", opener=opener2, cache_dir=str(tmp_path / "cache"))
    c = gh2.commit_pulls("o", "r", "abc123")
    assert c[0]["number"] == 1 and len(opener2.calls) == 0


def test_api_cache_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("LINELORE_CACHE", "off")
    assert resolve_cache_dir() is None
    opener = RecordingOpener([])
    gh = GitHub(token="t", opener=opener, cache_dir=False)
    gh.commit_pulls("o", "r", "abc")
    gh.commit_pulls("o", "r", "abc")
    assert len(opener.calls) == 1  # still memory-cached within process
    # disable memory too by clearing between — disk is off so second instance refetches
    opener2 = RecordingOpener([])
    gh2 = GitHub(token="t", opener=opener2, cache_dir=False)
    gh2.commit_pulls("o", "r", "abc")
    assert len(opener2.calls) == 1
