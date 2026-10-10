"""Minimal GitHub REST/GraphQL client using only the stdlib."""
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request


class GitHubError(RuntimeError):
    pass


def find_token():
    for var in ("LINELORE_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    if shutil.which("gh"):
        try:
            p = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
            if p.returncode == 0 and p.stdout.strip():
                return p.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return None


class GitHub:
    def __init__(self, token=None, api="https://api.github.com", opener=None):
        self.token = token
        self.api = api.rstrip("/")
        self._open = opener or urllib.request.urlopen

    def _req(self, method, path, body=None):
        url = path if path.startswith("http") else self.api + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "linelore")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with self._open(req, timeout=20) as r:
                return json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:200]
            if e.code in (403, 429) and "rate limit" in msg.lower():
                raise GitHubError("GitHub rate limit hit; set GH_TOKEN or run `gh auth login`")
            raise GitHubError("GitHub API %s %s -> %s %s" % (method, url, e.code, msg))
        except urllib.error.URLError as e:
            raise GitHubError("cannot reach GitHub: %s" % e.reason)

    def get(self, path):
        return self._req("GET", path)

    def commit_pulls(self, owner, repo, sha):
        return self.get("/repos/%s/%s/commits/%s/pulls" % (owner, repo, sha)) or []

    def pull_review_comments(self, owner, repo, number):
        return self.get("/repos/%s/%s/pulls/%d/comments?per_page=100" % (owner, repo, number)) or []

    def closing_issues(self, owner, repo, number):
        if not self.token:
            return []  # GraphQL requires auth
        q = ("query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n)"
             "{closingIssuesReferences(first:10){nodes{number title url state body}}}}}")
        res = self._req("POST", "/graphql", {"query": q, "variables": {"o": owner, "r": repo, "n": number}})
        try:
            return res["data"]["repository"]["pullRequest"]["closingIssuesReferences"]["nodes"] or []
        except (KeyError, TypeError):
            return []
