"""GitHub / GitHub Enterprise backend (REST + GraphQL, stdlib only)."""
import os
import shutil
import subprocess

from .forge import CommitNotFound, Forge, ForgeError, TOKEN_VARS, resolve_cache_dir  # noqa: F401

# v0.1/v0.2 name, kept so `from linelore.github import GitHubError` still works.
GitHubError = ForgeError


def find_token(host=None):
    """LINELORE_TOKEN / GH_TOKEN / GITHUB_TOKEN, else `gh auth token` for that host."""
    for var in TOKEN_VARS["github"]:
        if os.environ.get(var):
            return os.environ[var]
    if shutil.which("gh"):
        cmd = ["gh", "auth", "token"]
        if host and host != "github.com":
            cmd += ["--hostname", host]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if p.returncode == 0 and p.stdout.strip():
                return p.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return None


class GitHub(Forge):
    name = "github"
    token_vars = TOKEN_VARS["github"]

    def __init__(self, token=None, api="https://api.github.com", opener=None, cache_dir=None, web=None):
        super().__init__(token, api=api, opener=opener, cache_dir=cache_dir, web=web)

    def _headers(self):
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        return h

    @property
    def graphql_url(self):
        # github.com: api.github.com/graphql; GHES: https://host/api/graphql (not /api/v3/graphql)
        if self.api.endswith("/api/v3"):
            return self.api[: -len("/v3")] + "/graphql"
        return self.api + "/graphql"

    def commit_pulls(self, owner, repo, sha):
        try:
            return self.get("/repos/%s/%s/commits/%s/pulls" % (owner, repo, sha)) or []
        except ForgeError as e:
            code = getattr(e, "status", None)
            if code == 422 or (code == 404 and "commit" in (getattr(e, "body", "") or "").lower()):
                web_host = "github.com" if self.host == "api.github.com" else self.host
                raise CommitNotFound("commit %s isn't on %s/%s/%s (not pushed yet?)" % (sha[:10], web_host, owner, repo))
            if code == 404:
                hint = "private? set GH_TOKEN" if not self.token else "check --repo OWNER/REPO"
                raise ForgeError("%s/%s not found on %s (%s)"
                                 % (owner, repo, "github.com" if self.host == "api.github.com" else self.host, hint))
            raise

    def pull_review_comments(self, owner, repo, number):
        return self.get("/repos/%s/%s/pulls/%d/comments?per_page=100" % (owner, repo, number)) or []

    def closing_issues(self, owner, repo, number):
        if not self.token:
            return []  # GraphQL requires auth
        q = ("query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n)"
             "{closingIssuesReferences(first:10){nodes{number title url state body}}}}}")
        res = self._req("POST", self.graphql_url, {"query": q, "variables": {"o": owner, "r": repo, "n": number}})
        try:
            return res["data"]["repository"]["pullRequest"]["closingIssuesReferences"]["nodes"] or []
        except (KeyError, TypeError):
            return []
