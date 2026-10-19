"""GitLab and Gitea/Forgejo backends, forge detection, errors, cache, --open.

HTTP is faked with recorded (trimmed) real responses in tests/fixtures:
gitlab-org/cli MR !4112 on gitlab.com and dnkl/foot PR #2463 on codeberg.org.
"""
import io
import json
import os
import subprocess
import time
import urllib.error

import pytest

from linelore import cli
from linelore.forge import (EMPTY_TTL, CommitNotFound, ForgeError, UnknownForge, Unauthorized, describe_age,
                            empty_ttl, make_forge, resolve_forge, web_from_api)
from linelore.gitea import Gitea
from linelore.github import GitHub
from linelore.gitlab import GitLab
from linelore.gitops import merge_commit_for, parse_porcelain, parse_remote
from linelore.lore import build_lore, build_range_lore, closing_refs, excerpt, issue_refs
from linelore.render import to_text

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
GL_SHA = "28cd7b06fe62b5a25c9fd53c2bc88891297bdcd0"
GT_SHA = "d4896e386b3757264775e3ac2e1d1abc9d13a0c2"


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


class Router:
    """urllib-style opener: exact URL (or URL prefix ending in '*') -> (status, payload)."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.headers = []

    def __call__(self, req, timeout=20):
        url = req.full_url
        self.calls.append(url)
        self.headers.append(dict(req.header_items()))
        hit = self.routes.get(url)
        if hit is None:
            for k, v in self.routes.items():
                if k.endswith("*") and url.startswith(k[:-1]):
                    hit = v
                    break
        if hit is None:
            hit = (404, {"message": "404 Not Found (no fixture for %s)" % url})
        status, payload, headers = (hit + ({},))[:3]  # optional third item: response headers
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        if status >= 400:
            hdrs = {"RateLimit-Remaining": "0"} if status == 429 else {}
            raise urllib.error.HTTPError(url, status, "err", hdrs, io.BytesIO(body))

        class Resp:
            def __init__(self_inner):
                self_inner.headers = headers

            def read(self_inner):
                return body

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False
        return Resp()


def blame(sha, line, orig=None, filename="internal/commands/packages/download/download.go"):
    return {"sha": sha, "line": line, "orig_line": orig or line, "author": "A", "author_time": 1760000000,
            "summary": "s", "filename": filename, "content": "x", "uncommitted": False}


# ---------------------------------------------------------------- detection

@pytest.mark.parametrize("host,name,api,web", [
    ("github.com", "github", "https://api.github.com", "https://github.com"),
    ("ssh.github.com", "github", "https://api.github.com", "https://github.com"),
    ("github-work", "github", "https://api.github.com", "https://github.com"),   # ~/.ssh/config alias
    ("gitlab.com", "gitlab", "https://gitlab.com/api/v4", "https://gitlab.com"),
    ("altssh.gitlab.com", "gitlab", "https://gitlab.com/api/v4", "https://gitlab.com"),
    ("salsa.debian.org", "gitlab", "https://salsa.debian.org/api/v4", "https://salsa.debian.org"),
    ("gitlab.example.com", "gitlab", "https://gitlab.example.com/api/v4", "https://gitlab.example.com"),
    ("codeberg.org", "gitea", "https://codeberg.org/api/v1", "https://codeberg.org"),
    ("gitea.com", "gitea", "https://gitea.com/api/v1", "https://gitea.com"),
    ("git.forgejo.example.org", "gitea", "https://git.forgejo.example.org/api/v1", "https://git.forgejo.example.org"),
    ("github.corp.example", "github", "https://github.corp.example/api/v3", "https://github.corp.example"),
])
def test_detect_forge_from_host(host, name, api, web):
    spec = resolve_forge(host)
    assert (spec.name, spec.api, spec.web) == (name, api, web)


def test_unknown_host_needs_forge_flag():
    with pytest.raises(UnknownForge) as e:
        resolve_forge("git.example.com")
    assert "--forge gitlab" in str(e.value) and "git.example.com" in str(e.value)


def test_forge_flag_and_api_override():
    assert resolve_forge("git.example.com", forge="gitlab").api == "https://git.example.com/api/v4"
    assert resolve_forge("git.example.com", forge="forgejo").name == "gitea"
    s = resolve_forge("git.example.com", api="https://git.example.com/gitlab/api/v4/")
    assert (s.name, s.api, s.web) == ("gitlab", "https://git.example.com/gitlab/api/v4", "https://git.example.com/gitlab")
    assert resolve_forge("git.example.com", api="https://git.example.com/api/v1").name == "gitea"
    assert resolve_forge("ghe.corp", api="https://ghe.corp/api/v3").name == "github"
    # --forge beats the host; LINELORE_API is a GitHub (Enterprise) setting only
    assert resolve_forge("github.com", forge="gitea").name == "gitea"
    assert resolve_forge("ghe.corp", env_api="https://ghe.corp/api/v3").api == "https://ghe.corp/api/v3"
    assert resolve_forge("gitlab.com", env_api="https://ghe.corp/api/v3").api == "https://gitlab.com/api/v4"
    assert web_from_api("github", "https://api.github.com") == "https://github.com"


def test_ghes_graphql_url():
    assert GitHub(api="https://ghe.corp/api/v3", cache_dir=False).graphql_url == "https://ghe.corp/api/graphql"
    assert GitHub(cache_dir=False).graphql_url == "https://api.github.com/graphql"


def test_parse_remote_gitlab_subgroups():
    assert parse_remote("git@gitlab.com:group/sub/proj.git") == ("gitlab.com", "group", "sub/proj")
    assert parse_remote("https://codeberg.org/dnkl/foot.git") == ("codeberg.org", "dnkl", "foot")


def test_make_forge_picks_backend_and_token(monkeypatch):
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-x")
    monkeypatch.delenv("GITEA_TOKEN", raising=False)
    monkeypatch.setenv("FORGEJO_TOKEN", "fj-y")
    gl = make_forge(resolve_forge("gitlab.com"), cache_dir=False)
    gt = make_forge(resolve_forge("codeberg.org"), cache_dir=False)
    assert isinstance(gl, GitLab) and gl.token == "glpat-x"
    assert isinstance(gt, Gitea) and gt.token == "fj-y" and gt.title == "Forgejo"


# ------------------------------------------------------------------- GitLab

GL = "https://gitlab.com/api/v4/projects/gitlab-org%2Fcli"


def gitlab_routes(discussions=(200, None)):
    return {
        GL + "/repository/commits/%s/merge_requests" % GL_SHA: (200, fixture("gitlab_commit_mrs.json")),
        GL + "/merge_requests/4112/closes_issues?per_page=20": (200, fixture("gitlab_closes_issues.json")),
        GL + "/merge_requests/4112/discussions?per_page=100":
            discussions if discussions[1] is not None else (200, fixture("gitlab_discussions.json")),
    }


def test_gitlab_lore_end_to_end():
    r = Router(gitlab_routes())
    gl = GitLab("glpat-x", api="https://gitlab.com/api/v4", opener=r, cache_dir=False)
    lore = build_lore(blame(GL_SHA, 290, 313), "gitlab-org", "cli", gl, "internal/commands/packages/download/download.go")
    assert lore["forge"] == "gitlab" and lore["repo"] == "gitlab-org/cli"
    (mr,) = lore["pulls"]
    assert mr["number"] == 4112 and mr["state"] == "closed" and mr["merged_at"].startswith("2026-10-16")
    assert mr["url"] == "https://gitlab.com/gitlab-org/cli/-/merge_requests/4112" and mr["author"] == "jmrp"
    assert [i["number"] for i in mr["issues"]] == [8615] and mr["issues"][0]["state"] == "CLOSED"
    # only diff notes on this file, nearest the line, thread replies kept, system/general notes dropped
    assert [c["author"] for c in mr["review_comments"]] == ["jhebden", "jmrp"]
    assert all(c["near"] and c["line"] == 313 for c in mr["review_comments"])
    assert mr["review_comments"][0]["url"].endswith("/-/merge_requests/4112#note_1128")
    assert r.headers[0].get("Private-token") == "glpat-x"
    text = to_text(lore)
    assert "MR !4112" in text and "PR #" not in text
    assert "fixes #8615" in text and "[closed]" in text and "merged 2026-10-16" in text


def test_gitlab_anonymous_401_on_discussions_is_a_note_not_a_failure():
    r = Router(gitlab_routes(discussions=(401, {"message": "401 Unauthorized"})))
    gl = GitLab(None, api="https://gitlab.com/api/v4", opener=r, cache_dir=False)
    lore = build_lore(blame(GL_SHA, 290, 313), "gitlab-org", "cli", gl, "x")
    assert lore["pulls"][0]["issues"][0]["number"] == 8615
    assert lore["pulls"][0]["review_comments"] == []
    assert lore["notes"] == ["review comments skipped: gitlab.com only shows these to signed-in users; set GITLAB_TOKEN"]


def test_gitlab_subgroup_project_is_url_encoded():
    r = Router({"https://gitlab.com/api/v4/projects/group%2Fsub%2Fproj/repository/commits/abc/merge_requests": (200, [])})
    gl = GitLab(None, api="https://gitlab.com/api/v4", opener=r, cache_dir=False)
    assert gl.commit_pulls("group", "sub/proj", "abc") == []
    assert gl.issue_url("group/sub/proj", 3) == "https://gitlab.com/group/sub/proj/-/issues/3"


def test_gitlab_404s_are_explained():
    r = Router({GL + "/repository/commits/%s/merge_requests" % GL_SHA: (404, {"message": "404 Commit Not Found"}),
                "https://gitlab.com/api/v4/projects/nope%2Fnada/*": (404, {"message": "404 Project Not Found"})})
    gl = GitLab(None, api="https://gitlab.com/api/v4", opener=r, cache_dir=False)
    lore = build_lore(blame(GL_SHA, 1), "gitlab-org", "cli", gl, "x")
    assert lore["pulls"] == [] and "isn't on gitlab.com/gitlab-org/cli (not pushed yet?)" in lore["notes"][0]
    with pytest.raises(ForgeError) as e:
        gl.commit_pulls("nope", "nada", GL_SHA)
    assert "nope/nada not found on gitlab.com (private? set GITLAB_TOKEN)" in str(e.value)


def test_gitlab_open_mr_is_not_shown_as_merged():
    mr = dict(fixture("gitlab_commit_mrs.json")[0], state="opened", merged_at=None)
    r = Router({GL + "/repository/commits/abc/merge_requests": (200, [mr]),
                GL + "/merge_requests/4112/closes_issues?per_page=20": (200, []),
                GL + "/merge_requests/4112/discussions?per_page=100": (200, [])})
    gl = GitLab(None, api="https://gitlab.com/api/v4", opener=r, cache_dir=False)
    lore = build_lore(blame("abc", 1), "gitlab-org", "cli", gl, "x")
    assert lore["pulls"][0]["state"] == "open"
    assert "(@jmrp, still open)" in to_text(lore)


# -------------------------------------------------------------- Gitea/Forgejo

CB = "https://codeberg.org/api/v1/repos/dnkl/foot"


def gitea_routes(**extra):
    routes = {
        CB + "/commits/%s/pull" % GT_SHA: (200, fixture("gitea_commit_pull.json")),
        CB + "/issues/2462": (200, fixture("gitea_issue.json")),
        CB + "/pulls/2463/reviews?limit=50&page=1": (200, fixture("gitea_reviews.json"), {"X-Total-Count": "1"}),
        CB + "/pulls/2463/reviews/1759028/comments": (200, fixture("gitea_review_comments.json")),
    }
    routes.update(extra)
    return routes


def test_gitea_lore_end_to_end():
    r = Router(gitea_routes())
    gt = Gitea("tok", api="https://codeberg.org/api/v1", opener=r, cache_dir=False)
    lore = build_lore(blame(GT_SHA, 5, 5, filename=".gitignore"), "dnkl", "foot", gt, ".gitignore")
    assert lore["forge"] == "gitea"
    (pr,) = lore["pulls"]
    assert pr["number"] == 2463 and pr["author"] == "celinakalus" and pr["merged_at"].startswith("2026-09-10")
    assert pr["url"] == "https://codeberg.org/dnkl/foot/pulls/2463"
    assert "Signed-off-by" not in pr["body"]  # trailers are noise in an excerpt
    # Fixes #2462 in the body -> looked up as a real issue, not a placeholder
    assert pr["issues"] == [{"number": 2462, "title": "Colored, cleared cells are deleted when resizing the window",
                             "url": "https://codeberg.org/dnkl/foot/issues/2462", "state": "CLOSED",
                             "body": pr["issues"][0]["body"]}]
    assert pr["mentions"] == []
    assert [c["author"] for c in pr["review_comments"]] == ["cismonx", "K4"] and pr["review_comments"][0]["line"] == 5
    assert r.headers[0].get("Authorization") == "token tok"
    assert "PR #2463" in to_text(lore)


def test_gitea_no_pr_then_merge_commit_fallback():
    merge = "f4da46350e47d1094136b264d76fcf9caeb77a55"
    r = Router(gitea_routes())
    r.routes.update({
        CB + "/commits/%s/pull" % ("b" * 40): (404, {"message": "pull request does not exist"}),
        CB: (200, {"full_name": "dnkl/foot"}),
        CB + "/git/commits/" + "b" * 40: (200, {"sha": "b" * 40}),
        CB + "/commits/%s/pull" % merge: (200, fixture("gitea_commit_pull.json")),
    })
    gt = Gitea(None, api="https://codeberg.org/api/v1", opener=r, cache_dir=False)
    seen = []

    def lookup(sha):
        seen.append(sha)
        return merge
    lore = build_lore(blame("b" * 40, 1), "dnkl", "foot", gt, "grid.c", merge_lookup=lookup)
    assert seen == ["b" * 40] and lore["pulls"][0]["number"] == 2463 and lore["notes"] == []
    # without a merge commit: an honest "no pull request" note
    lore = build_lore(blame("b" * 40, 1), "dnkl", "foot", gt, "grid.c", merge_lookup=lambda s: None)
    assert lore["notes"] == ["no pull request found for this commit (pushed directly?)"]


def test_gitea_404s_are_explained():
    r = Router({CB + "/commits/%s/pull" % ("c" * 40): (404, {"message": "pull request does not exist"}),
                CB: (200, {"full_name": "dnkl/foot"}),
                "https://codeberg.org/api/v1/repos/dnkl/gone/*": (404, {"message": "The target couldn't be found."})})
    gt = Gitea(None, api="https://codeberg.org/api/v1", opener=r, cache_dir=False)
    with pytest.raises(CommitNotFound) as e:
        gt.commit_pulls("dnkl", "foot", "c" * 40)
    assert "isn't on codeberg.org/dnkl/foot (not pushed yet?)" in str(e.value)
    with pytest.raises(ForgeError) as e:
        gt.commit_pulls("dnkl", "gone", "c" * 40)
    assert "dnkl/gone not found on codeberg.org (private? set FORGEJO_TOKEN)" in str(e.value)


def test_gitea_no_pr_answer_is_cached(tmp_path):
    sha = "d" * 40
    routes = {CB + "/commits/%s/pull" % sha: (404, {"message": "pull request does not exist"}),
              CB: (200, {"full_name": "dnkl/foot"}), CB + "/git/commits/" + sha: (200, {"sha": sha})}
    r = Router(routes)
    assert Gitea(None, api="https://codeberg.org/api/v1", opener=r, cache_dir=str(tmp_path)).commit_pulls("dnkl", "foot", sha) == []
    r2 = Router(routes)
    assert Gitea(None, api="https://codeberg.org/api/v1", opener=r2, cache_dir=str(tmp_path)).commit_pulls("dnkl", "foot", sha) == []
    assert len(r.calls) == 3 and r2.calls == []


# ------------------------------------------- Gitea review paging (issue #4)

REVIEWS = CB + "/pulls/2463/reviews?limit=50&page=%d"


def fake_reviews(n, with_comments=()):
    return [{"id": 9000 + i, "comments_count": 1 if i in with_comments else 0} for i in range(n)]


def comment_route(i, path="grid.c", line=930):
    return (CB + "/pulls/2463/reviews/%d/comments" % (9000 + i),
            (200, [{"path": path, "position": line, "body": "review %d" % i, "user": {"login": "r%d" % i},
                    "html_url": "https://codeberg.org/dnkl/foot/pulls/2463#c%d" % i}]))


def paged(reviews, pages, headers=lambda page, last: {}):
    routes = {}
    for page in range(1, pages + 1):
        chunk = reviews[(page - 1) * 50: page * 50]
        routes[REVIEWS % page] = (200, chunk, headers(page, pages))
    return routes


def test_gitea_reviews_page_by_total_count(tmp_path):
    reviews = fake_reviews(120, with_comments={3, 77, 119})  # the line's comment lives on page 3
    routes = paged(reviews, 3, lambda page, last: {"X-Total-Count": "120"})
    routes.update(dict(comment_route(i) for i in (3, 77, 119)))
    r = Router(routes)
    gt = Gitea(None, api="https://codeberg.org/api/v1", opener=r, cache_dir=str(tmp_path))
    comments = gt.pull_review_comments("dnkl", "foot", 2463)
    assert [c["body"] for c in comments] == ["review 3", "review 77", "review 119"]
    assert [u for u in r.calls if "/reviews?" in u] == [REVIEWS % 1, REVIEWS % 2, REVIEWS % 3]  # no 4th probe
    assert gt.pop_notices() == []
    # the whole list is one cache entry: a second run reads no review pages at all
    r2 = Router({})
    assert len(Gitea(None, api="https://codeberg.org/api/v1", opener=r2, cache_dir=str(tmp_path))
               .pull_review_comments("dnkl", "foot", 2463)) == 3
    assert r2.calls == []


def test_gitea_reviews_page_by_link_and_without_headers():
    reviews = fake_reviews(70, with_comments={69})
    nxt = '<https://internal:3000/api/v1/repos/dnkl/foot/pulls/2463/reviews?limit=50&page=2>; rel="next"'
    routes = paged(reviews, 2, lambda page, last: {"Link": nxt} if page < last else {"Link": '<x>; rel="first"'})
    routes.update([comment_route(69)])
    r = Router(routes)
    assert [c["body"] for c in Gitea(None, api="https://codeberg.org/api/v1", opener=r, cache_dir=False)
            .pull_review_comments("dnkl", "foot", 2463)] == ["review 69"]
    # page URLs are ours, never the Link target (a wrong ROOT_URL must not get the token)
    assert all(u.startswith(CB) for u in r.calls) and len([u for u in r.calls if "/reviews?" in u]) == 2
    # no paging headers at all: keep reading until a page comes back empty
    routes = paged(reviews, 2)
    routes[REVIEWS % 3] = (200, [])
    routes.update([comment_route(69)])
    r = Router(routes)
    assert len(Gitea(None, api="https://codeberg.org/api/v1", opener=r, cache_dir=False)
               .pull_review_comments("dnkl", "foot", 2463)) == 1
    assert [u for u in r.calls if "/reviews?" in u] == [REVIEWS % 1, REVIEWS % 2, REVIEWS % 3]


def test_gitea_server_ignoring_page_param_does_not_loop():
    r = Router({CB + "/pulls/2463/reviews?*": (200, fake_reviews(50))})
    Gitea(None, api="https://codeberg.org/api/v1", opener=r, cache_dir=False).pull_review_comments("dnkl", "foot", 2463)
    assert len(r.calls) == 2  # page 2 repeated page 1: stop


def test_gitea_review_page_cap_is_a_note(tmp_path):
    reviews = fake_reviews(812, with_comments={10})
    routes = gitea_routes()
    routes.update(paged(reviews, 17, lambda page, last: {"X-Total-Count": "812"}))
    routes.update([comment_route(10)])
    r = Router(routes)
    gt = Gitea(None, api="https://codeberg.org/api/v1", opener=r, cache_dir=str(tmp_path))
    lore = build_lore(blame(GT_SHA, 930, filename="grid.c"), "dnkl", "foot", gt, "grid.c")
    assert len([u for u in r.calls if "/reviews?" in u]) == 10
    assert lore["pulls"][0]["review_comments"][0]["body"] == "review 10"
    note = "PR #2463 has 812 reviews; only the first 500 were read for review comments"
    assert lore["notes"] == [note]
    assert note in to_text(lore)
    # the note survives a cache hit
    gt = Gitea(None, api="https://codeberg.org/api/v1", opener=Router({}), cache_dir=str(tmp_path))
    assert build_lore(blame(GT_SHA, 930, filename="grid.c"), "dnkl", "foot", gt, "grid.c")["notes"] == [note]


def test_gitea_review_thread_cap_reads_the_newest():
    reviews = fake_reviews(60)
    for rv in reviews:
        rv["comments_count"] = 2
    routes = paged(reviews, 2, lambda page, last: {"X-Total-Count": "60"})
    routes.update(dict(comment_route(i) for i in range(60)))
    r = Router(routes)
    gt = Gitea(None, api="https://codeberg.org/api/v1", opener=r, cache_dir=False)
    comments = gt.pull_review_comments("dnkl", "foot", 2463)
    assert [c["body"] for c in comments][:1] == ["review 10"] and len(comments) == 50
    assert gt.pop_notices() == ["PR #2463 has 60 reviews with inline comments; only the newest 50 were read"]


# --------------------------------------------------------- errors and cache

def test_rate_limit_and_auth_messages():
    gl = GitLab(None, api="https://gitlab.com/api/v4", opener=Router({"*": (429, {"message": "Retry later"})}), cache_dir=False)
    with pytest.raises(ForgeError) as e:
        gl.commit_pulls("a", "b", "c")
    assert str(e.value) == "GitLab rate limit hit on gitlab.com; set GITLAB_TOKEN"
    gh = GitHub(None, opener=Router({"*": (403, {"message": "API rate limit exceeded for 1.2.3.4"})}), cache_dir=False)
    with pytest.raises(ForgeError) as e:
        gh.commit_pulls("a", "b", "c")
    assert "GitHub rate limit hit" in str(e.value) and "gh auth login" in str(e.value)
    gt = Gitea("bad", api="https://codeberg.org/api/v1", opener=Router({"*": (401, {"message": "token is required"})}), cache_dir=False)
    with pytest.raises(Unauthorized) as e:
        gt.commit_pulls("a", "b", "c")
    assert str(e.value) == "Forgejo rejected the token (401 on codeberg.org); check FORGEJO_TOKEN"


def test_github_404_and_422():
    gh = GitHub(None, opener=Router({"https://api.github.com/repos/o/gone/commits/abc/pulls": (404, {"message": "Not Found"}),
                                     "https://api.github.com/repos/o/r/commits/abc/pulls": (422, {"message": "No commit found for SHA: abc"})}),
                cache_dir=False)
    with pytest.raises(ForgeError) as e:
        gh.commit_pulls("o", "gone", "abc")
    assert str(e.value) == "o/gone not found on github.com (private? set GH_TOKEN)"
    with pytest.raises(CommitNotFound) as e:
        gh.commit_pulls("o", "r", "abc")
    assert str(e.value) == "commit abc isn't on github.com/o/r (not pushed yet?)"


def test_html_instead_of_json_points_at_api_flag():
    gl = GitLab(None, api="https://git.example.com", opener=Router({"*": (200, b"<html>login</html>")}), cache_dir=False)
    with pytest.raises(ForgeError) as e:
        gl.get("/projects/x")
    assert "did not answer with JSON" in str(e.value) and "/api/v4" in str(e.value)


def test_unreachable_host():
    def boom(req, timeout=20):
        raise urllib.error.URLError("Name or service not known")
    gt = Gitea(None, api="https://git.nowhere.invalid/api/v1", opener=boom, cache_dir=False)
    with pytest.raises(ForgeError) as e:
        gt.get("/version")
    assert str(e.value) == "cannot reach Gitea (git.nowhere.invalid): Name or service not known"


def test_cache_is_per_forge(tmp_path):
    r1 = Router({"*": (200, [])})
    GitLab(None, api="https://x.example/api", opener=r1, cache_dir=str(tmp_path)).get("/same")
    r2 = Router({"*": (200, [])})
    Gitea(None, api="https://x.example/api", opener=r2, cache_dir=str(tmp_path)).get("/same")
    assert len(r1.calls) == 1 and len(r2.calls) == 1  # same host + path, different forge: no cross-talk


# ------------------------------------------- empty answers expire (issue #3)

GH_PULLS = "https://api.github.com/repos/o/r/commits/%s/pulls" % ("e" * 40)
GH_PR = {"number": 41, "title": "Add the thing", "html_url": "https://github.com/o/r/pull/41",
         "user": {"login": "dev"}, "merged_at": "2026-10-19T08:00:00Z", "state": "closed", "body": ""}


def later(seconds):
    start = time.time()
    return lambda: start + seconds


def test_no_pr_answer_expires_and_the_new_pr_is_found(tmp_path):
    cache = str(tmp_path)
    # 1. the commit is still on a feature branch: GitHub says "no PRs"
    r = Router({GH_PULLS: (200, [])})
    assert GitHub("t", opener=r, cache_dir=cache).commit_pulls("o", "r", "e" * 40) == []
    # 2. the PR is opened and merged; ten minutes later the cached "no PR" still answers, and says so
    r = Router({GH_PULLS: (200, [GH_PR]), "*": (200, {})})
    gh = GitHub("t", opener=r, cache_dir=cache)
    gh.clock = later(10 * 60 + 30)
    lore = build_lore(blame("e" * 40, 3), "o", "r", gh, "app.py")
    assert lore["pulls"] == [] and r.calls == []
    assert lore["notes"] == ["no pull request found for this commit (pushed directly?); "
                             "cached 10 min ago (LINELORE_CACHE_EMPTY_TTL=0 to re-check)"]
    # 3. after the hour the empty answer is stale: linelore asks again and finds the PR
    gh = GitHub("t", opener=r, cache_dir=cache)
    gh.clock = later(EMPTY_TTL + 1)
    assert [p["number"] for p in gh.commit_pulls("o", "r", "e" * 40)] == [41] and r.calls == [GH_PULLS]
    # 4. a real answer keeps the old behaviour: cached for good, no expiry
    r = Router({})
    gh = GitHub("t", opener=r, cache_dir=cache)
    gh.clock = later(365 * 24 * 3600)
    assert [p["number"] for p in gh.commit_pulls("o", "r", "e" * 40)] == [41] and r.calls == []


def test_gitea_no_pr_expires_and_unpushed_commit_is_not_cached(tmp_path):
    sha = "f" * 40
    pull = CB + "/commits/%s/pull" % sha
    no_pr = (404, {"message": "pull request does not exist"})
    # not pushed yet: commit-not-found must not stick once it is pushed
    r = Router({pull: no_pr, CB: (200, {"full_name": "dnkl/foot"})})
    with pytest.raises(CommitNotFound):
        Gitea(None, api="https://codeberg.org/api/v1", opener=r, cache_dir=str(tmp_path)).commit_pulls("dnkl", "foot", sha)
    r = Router({pull: no_pr, CB: (200, {"full_name": "dnkl/foot"}), CB + "/git/commits/" + sha: (200, {"sha": sha})})
    assert Gitea(None, api="https://codeberg.org/api/v1", opener=r, cache_dir=str(tmp_path)).commit_pulls("dnkl", "foot", sha) == []
    # the PR shows up; within the hour the cached "no PR" answers, after it the PR is found
    r = Router({pull: (200, fixture("gitea_commit_pull.json"))})
    gt = Gitea(None, api="https://codeberg.org/api/v1", opener=r, cache_dir=str(tmp_path))
    gt.clock = later(EMPTY_TTL - 60)
    assert gt.commit_pulls("dnkl", "foot", sha) == [] and r.calls == []
    gt = Gitea(None, api="https://codeberg.org/api/v1", opener=r, cache_dir=str(tmp_path))
    gt.clock = later(EMPTY_TTL + 1)
    assert [p["number"] for p in gt.commit_pulls("dnkl", "foot", sha)] == [2463] and r.calls == [pull]


def test_empty_ttl_setting(tmp_path, monkeypatch):
    assert empty_ttl() == EMPTY_TTL == 3600
    for raw, want in (("600", 600), ("0", 0), ("2.5", 2.5), ("-5", EMPTY_TTL), ("soon", EMPTY_TTL), ("", EMPTY_TTL),
                      ("nan", EMPTY_TTL), ("inf", EMPTY_TTL), ("-inf", EMPTY_TTL)):
        monkeypatch.setenv("LINELORE_CACHE_EMPTY_TTL", raw)
        assert empty_ttl() == want
    # 0: empty answers never reach the disk; real ones still do
    monkeypatch.setenv("LINELORE_CACHE_EMPTY_TTL", "0")
    gh = GitHub("t", opener=Router({GH_PULLS: (200, []), "*": (200, [GH_PR])}), cache_dir=str(tmp_path))
    gh.commit_pulls("o", "r", "e" * 40)
    assert not list(tmp_path.rglob("*.json"))
    gh.get("/repos/o/r/pulls/41/comments?per_page=100")
    assert len(list(tmp_path.rglob("*.json"))) == 1


def test_cached_age_note_survives_a_memory_hit(tmp_path):
    GitHub("t", opener=Router({GH_PULLS: (200, [])}), cache_dir=str(tmp_path)).commit_pulls("o", "r", "e" * 40)
    r = Router({})
    gh = GitHub("t", opener=r, cache_dir=str(tmp_path))
    gh.clock = later(10 * 60 + 30)
    first = build_lore(blame("e" * 40, 3), "o", "r", gh, "app.py")  # from disk
    gh.clock = later(12 * 60 + 30)
    second = build_lore(blame("e" * 40, 9), "o", "r", gh, "app.py")  # same answer, now from memory
    assert r.calls == []
    assert first["notes"][0].endswith("cached 10 min ago (LINELORE_CACHE_EMPTY_TTL=0 to re-check)")
    assert second["notes"][0].endswith("cached 12 min ago (LINELORE_CACHE_EMPTY_TTL=0 to re-check)")
    # an empty answer fetched in this process is fresh: no "cached" in the note
    r = Router({GH_PULLS.replace("e" * 40, "9" * 40): (200, [])})
    gh = GitHub("t", opener=r, cache_dir=str(tmp_path))
    for _ in range(2):
        lore = build_lore(blame("9" * 40, 3), "o", "r", gh, "app.py")
        assert lore["notes"] == ["no pull request found for this commit (pushed directly?)"]
    assert len(r.calls) == 1


def test_empty_answer_from_the_future_is_stale(tmp_path):
    r = Router({GH_PULLS: (200, [])})
    GitHub("t", opener=r, cache_dir=str(tmp_path)).commit_pulls("o", "r", "e" * 40)
    gh = GitHub("t", opener=r, cache_dir=str(tmp_path))
    gh.clock = later(-600)  # the clock went back: don't trust the file for another hour+
    gh.commit_pulls("o", "r", "e" * 40)
    assert len(r.calls) == 2


def test_describe_age():
    assert [describe_age(s) for s in (5, 60, 59 * 60 + 59, 3 * 3600)] == ["just now", "1 min ago", "59 min ago", "3 h ago"]


# ------------------------------------------------------------ text helpers

def test_closing_refs_urls_and_subgroups():
    assert closing_refs("Fixes https://codeberg.org/dnkl/foot/issues/2462", "dnkl", "foot") == [("dnkl/foot", 2462)]
    assert closing_refs("Closes: https://gitlab.com/g/sub/p/-/issues/3 and fixes #4", "g", "sub/p") == [("g/sub/p", 3), ("g/sub/p", 4)]
    assert issue_refs("see group/sub/proj#12", "o", "r") == [("group/sub/proj", 12)]


def test_excerpt_drops_template_noise():
    body = "## Description\n\nIt [broke](https://x.example/a) here ![img](u.png).\n\nSigned-off-by: A <a@x>\nCo-authored-by: B <b@x>"
    assert excerpt(body) == "It broke here ."
    assert excerpt("#123 is the issue") == "#123 is the issue"


# ------------------------------------------------------------ CLI and --open

def _git(cwd, *a):
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@e", *a], cwd=cwd, check=True, capture_output=True)


def _repo(tmp_path, remote):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "f.txt").write_text("one\ntwo\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "add f")
    _git(tmp_path, "remote", "add", "origin", remote)
    return str(tmp_path / "f.txt")


class FakeForge:
    name, title, pr_by_merge_commit_only = "gitlab", "GitLab", False

    def __init__(self, pulls):
        self.pulls = pulls

    def commit_pulls(self, o, r, sha):
        return self.pulls

    def closing_issues(self, o, r, n):
        return []

    def pull_review_comments(self, o, r, n):
        return []

    def issue_url(self, full, n):
        return "https://gitlab.com/%s/-/issues/%d" % (full, n)


MR = {"number": 7, "title": "Make it so", "html_url": "https://gitlab.com/g/p/-/merge_requests/7",
      "user": {"login": "m"}, "merged_at": "2026-10-01T00:00:00Z", "state": "closed", "body": ""}


def test_cli_gitlab_remote_json_has_forge(tmp_path, capsys, monkeypatch):
    f = _repo(tmp_path, "git@gitlab.com:g/p.git")
    monkeypatch.setattr(cli, "make_forge", lambda spec: FakeForge([MR]))
    assert cli.main([f + ":2", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["forge"] == "gitlab" and out["repo"] == "g/p" and out["pulls"][0]["number"] == 7


def test_cli_offline_keeps_forge_and_makes_no_calls(tmp_path, capsys, monkeypatch):
    f = _repo(tmp_path, "https://codeberg.org/dnkl/foot.git")
    monkeypatch.setattr(cli, "make_forge", lambda spec: pytest.fail("no forge offline"))
    assert cli.main([f + ":1", "--offline", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["forge"] == "gitea" and out["notes"] == ["offline: showing local commit only"]


def test_cli_no_remote_says_so(tmp_path, capsys):
    _git(tmp_path, "init", "-q")
    (tmp_path / "f.txt").write_text("x\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "c")
    assert cli.main([str(tmp_path / "f.txt") + ":1", "--json"]) == 0
    note = json.loads(capsys.readouterr().out)["notes"][0]
    assert note.startswith("no forge remote to read the repo from (origin)") and "--repo" in note


def test_gitlab_commit_url_from_spec():
    assert resolve_forge("gitlab.com").commit_url("g/p", "abc") == "https://gitlab.com/g/p/-/commit/abc"
    assert resolve_forge("github.com").commit_url("o/r", "abc") == "https://github.com/o/r/commit/abc"


def test_cli_unknown_host_is_a_friendly_note(tmp_path, capsys, monkeypatch):
    f = _repo(tmp_path, "git@git.example.com:team/svc.git")
    monkeypatch.setattr(cli, "make_forge", lambda spec: pytest.fail("no lookup for an unknown host"))
    assert cli.main([f + ":1", "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "can't tell which forge git.example.com runs; pass --forge gitlab" in out


def test_cli_forge_failure_exit_3_without_offline_note(tmp_path, capsys, monkeypatch):
    f = _repo(tmp_path, "git@gitlab.com:g/p.git")

    class Down(FakeForge):
        def commit_pulls(self, o, r, sha):
            raise ForgeError("cannot reach GitLab (gitlab.com): timed out")
    monkeypatch.setattr(cli, "make_forge", lambda spec: Down([]))
    assert cli.main([f + ":1", "--no-color"]) == 3
    out = capsys.readouterr().out
    assert "lookup failed: cannot reach GitLab (gitlab.com): timed out" in out and "offline" not in out


# ------------------------------------------------ Forgejo by name (issue #5)

SELF = "https://git.example.com/api/v1"


def test_forgejo_name_from_flag_and_host():
    spec = resolve_forge("git.example.com", forge="forgejo")
    assert (spec.name, spec.flavor, spec.title) == ("gitea", "forgejo", "Forgejo")
    assert resolve_forge("git.example.com", forge="gitea").title == "Gitea"
    for host, title in (("git.forgejo.example.org", "Forgejo"), ("forgejo-dev.corp.example", "Forgejo"),
                        ("codeberg.org", "Forgejo"), ("gitea.com", "Gitea"), ("notforgejo.example", "Gitea")):
        assert resolve_forge(host, forge="gitea").title == title, host
    gt = make_forge(spec, opener=Router({"*": (401, {"message": "token is required"})}), cache_dir=False, token="bad")
    with pytest.raises(Unauthorized) as e:
        gt.commit_pulls("team", "svc", "a" * 40)
    assert str(e.value) == "Forgejo rejected the token (401 on git.example.com); check FORGEJO_TOKEN"
    assert not any(u.endswith("/version") for u in gt._open.calls)  # the flag said so: nothing to ask


@pytest.mark.parametrize("version,title,var", [
    ("11.0.1+gitea-1.22.0", "Forgejo", "FORGEJO_TOKEN"),
    ("1.22.3", "Gitea", "GITEA_TOKEN"),
])
def test_self_hosted_error_asks_version_once(tmp_path, version, title, var):
    r = Router({SELF + "/version": (200, {"version": version}), "*": (401, {"message": "token is required"})})
    gt = Gitea("bad", api=SELF, opener=r, cache_dir=str(tmp_path))
    for _ in range(2):
        with pytest.raises(Unauthorized) as e:
            gt.commit_pulls("team", "svc", "a" * 40)
        assert str(e.value) == "%s rejected the token (401 on git.example.com); check %s" % (title, var)
    assert r.calls.count(SELF + "/version") == 1
    probe = r.headers[r.calls.index(SELF + "/version")]
    assert "Authorization" not in probe and gt.token == "bad"  # asked anonymously, token restored
    # cached per host: a later run doesn't ask again
    r2 = Router({"*": (401, {"message": "token is required"})})
    with pytest.raises(Unauthorized, match="^%s rejected" % title):
        Gitea("bad", api=SELF, opener=r2, cache_dir=str(tmp_path)).commit_pulls("team", "svc", "a" * 40)
    assert SELF + "/version" not in r2.calls


def test_version_probe_never_gets_in_the_way():
    # /version itself fails: still a clean "Gitea" message, asked once
    r = Router({SELF + "/version": (500, {"message": "boom"}), "*": (401, {"message": "token is required"})})
    gt = Gitea("bad", api=SELF, opener=r, cache_dir=False)
    for _ in range(2):
        with pytest.raises(Unauthorized, match=r"^Gitea rejected the token \(401 on git.example.com\); check GITEA_TOKEN$"):
            gt.commit_pulls("team", "svc", "a" * 40)
    assert r.calls.count(SELF + "/version") == 1
    # a lookup that works (here: "no PR") never asks
    sha = "a" * 40
    r = Router({SELF + "/repos/team/svc/commits/%s/pull" % sha: (404, {"message": "pull request does not exist"}),
                SELF + "/repos/team/svc": (200, {"full_name": "team/svc"}),
                SELF + "/repos/team/svc/git/commits/" + sha: (200, {"sha": sha})})
    lore = build_lore(blame(sha, 1), "team", "svc", Gitea(None, api=SELF, opener=r, cache_dir=False), "f.c")
    assert lore["notes"] == ["no pull request found for this commit (pushed directly?)"]
    assert SELF + "/version" not in r.calls
    # an unreachable host is not asked a second time
    calls = []

    def down(req, timeout=20):
        calls.append(req.full_url)
        raise urllib.error.URLError("Name or service not known")
    with pytest.raises(ForgeError, match="^cannot reach Gitea"):
        Gitea(None, api=SELF, opener=down, cache_dir=False).get("/repos/team/svc")
    assert len(calls) == 1


def test_cli_forge_forgejo_keeps_json_forge_gitea(tmp_path, capsys, monkeypatch):
    for var in ("GITEA_TOKEN", "FORGEJO_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    f = _repo(tmp_path, "git@git.example.com:team/svc.git")
    r = Router({SELF + "/repos/team/svc": (404, {"message": "The target couldn't be found."})})
    monkeypatch.setattr(cli, "make_forge", lambda spec: make_forge(spec, opener=r, cache_dir=False))
    assert cli.main([f + ":1", "--forge", "forgejo", "--json"]) == 3
    out = json.loads(capsys.readouterr().out)
    assert out["forge"] == "gitea"  # the API family, as documented; the name only shows in messages
    assert out["notes"] == ["lookup failed: team/svc not found on git.example.com (private? set FORGEJO_TOKEN)"]


@pytest.fixture
def browser(monkeypatch):
    opened = []
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(cli.webbrowser, "open", lambda url, new=0: opened.append(url) or True)
    return opened


def test_open_launches_the_mr(tmp_path, capsys, monkeypatch, browser):
    f = _repo(tmp_path, "git@gitlab.com:g/p.git")
    monkeypatch.setattr(cli, "make_forge", lambda spec: FakeForge([MR]))
    assert cli.main([f + ":2", "--open", "--no-color"]) == 0
    assert browser == ["https://gitlab.com/g/p/-/merge_requests/7"]
    assert "opened MR !7 in your browser" in capsys.readouterr().err


def test_open_range_picks_most_recently_merged(tmp_path, capsys, monkeypatch, browser):
    _repo(tmp_path, "git@gitlab.com:g/p.git")
    (tmp_path / "f.txt").write_text("one\nTWO\n")
    _git(tmp_path, "commit", "-qam", "second")
    old = dict(MR, number=3, html_url="https://gitlab.com/g/p/-/merge_requests/3", merged_at="2025-01-01T00:00:00Z")

    root = subprocess.run(["git", "rev-list", "--max-parents=0", "HEAD"], cwd=tmp_path,
                          capture_output=True, text=True).stdout.strip()

    class PerSha(FakeForge):  # line 1 -> old MR !3 (2025), line 2 -> MR !7 (2026)
        def commit_pulls(self, o, r, sha):
            return [old] if sha == root else [MR]
    monkeypatch.setattr(cli, "make_forge", lambda spec: PerSha([]))
    assert cli.main([str(tmp_path / "f.txt") + ":1-2", "--open", "--no-color"]) == 0
    assert browser == ["https://gitlab.com/g/p/-/merge_requests/7"]


def test_open_without_pr_opens_the_commit(tmp_path, capsys, monkeypatch, browser):
    f = _repo(tmp_path, "https://codeberg.org/dnkl/foot.git")
    assert cli.main([f + ":1", "--open", "--offline", "--no-color"]) == 0
    assert len(browser) == 1 and browser[0].startswith("https://codeberg.org/dnkl/foot/commit/")


def test_open_on_headless_box_prints_the_url(tmp_path, capsys, monkeypatch):
    f = _repo(tmp_path, "git@gitlab.com:g/p.git")
    for var in ("DISPLAY", "WAYLAND_DISPLAY", "BROWSER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(cli.sys, "platform", "linux")
    monkeypatch.setattr(cli.webbrowser, "open", lambda *a, **k: pytest.fail("must not start a console browser"))
    monkeypatch.setattr(cli, "make_forge", lambda spec: FakeForge([MR]))
    assert cli.main([f + ":2", "--open", "--json"]) == 0
    cap = capsys.readouterr()
    json.loads(cap.out)  # stdout stays pure JSON
    assert "no browser to open here; MR !7 is at https://gitlab.com/g/p/-/merge_requests/7" in cap.err


def test_open_demo_explains(capsys, browser):
    assert cli.main(["demo", "--open", "--no-color"]) == 0
    assert browser == [] and "nothing to open" in capsys.readouterr().err


# ------------------------------------------------------- merge commit lookup

def test_merge_commit_for(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a").write_text("1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "feature")
    (tmp_path / "b").write_text("2\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "feature work")
    feat = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    _git(tmp_path, "checkout", "-q", "main")
    (tmp_path / "c").write_text("3\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "direct on main")
    direct = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    _git(tmp_path, "merge", "-q", "--no-ff", "feature", "-m", "Merge feature")
    merge = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    assert merge_commit_for(feat, cwd=str(tmp_path)) == merge
    assert merge_commit_for(direct, cwd=str(tmp_path)) is None  # never blame a later merge for a direct push
    assert merge_commit_for(merge, cwd=str(tmp_path)) is None


def test_range_lore_carries_forge():
    rows = parse_porcelain("""%s 1 1 1
author A
author-time 1
summary s
filename f
\tx
""" % ("e" * 40))
    lore = build_range_lore([{"blame": rows[0], "lines": [1]}], "g", "p", FakeForge([MR]), "f", 1, 1)
    assert lore["forge"] == "gitlab" and lore["commits"][0]["pulls"][0]["number"] == 7


def test_range_text_does_not_repeat_a_shared_pr():
    pr = {"number": 540, "title": "Text reflow performance", "url": "u", "author": "dnkl", "merged_at": "2021-06-04",
          "state": "closed", "body": "Instead of walking the old grid", "issues": [], "mentions": ["dnkl/foot#504"],
          "review_comments": []}
    b1 = {"sha": "a" * 40, "line": 1, "author": "D", "author_time": 1, "summary": "one", "content": "x"}
    b2 = dict(b1, sha="b" * 40, line=2, summary="two")
    lore = {"forge": "gitea", "path": "grid.c", "range": {"start": 1, "end": 2}, "blame": b1, "pulls": [pr],
            "commits": [{"blame": b1, "lines": [1], "pulls": [pr], "notes": []},
                        {"blame": b2, "lines": [2], "pulls": [pr], "notes": []}],
            "notes": ["2 unique commits in lines 1–2"]}
    text = to_text(lore)
    assert text.count("Instead of walking") == 1 and "PR #540  Text reflow performance  (same PR as above)" in text
    assert "note" not in text  # the commit count is already in the heading
