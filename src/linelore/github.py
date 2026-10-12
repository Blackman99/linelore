"""Minimal GitHub REST/GraphQL client using only the stdlib.

Responses are cached in memory for the life of the process, and optionally on
disk under the cache directory (see resolve_cache_dir) keyed by API host +
path so repeated lookups of the same commit sha do not re-hit the network.
"""
import hashlib
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


def resolve_cache_dir(explicit=None):
    """Return a disk cache directory, or None to disable disk caching.

    Priority: explicit arg → LINELORE_CACHE env → XDG_CACHE_HOME/linelore
    → ~/.cache/linelore. Set LINELORE_CACHE to 0 / off / none / false to disable.
    """
    raw = explicit if explicit is not None else os.environ.get("LINELORE_CACHE")
    if raw is not None:
        v = str(raw).strip()
        if v.lower() in ("0", "off", "none", "false", "no", ""):
            return None
        return os.path.expanduser(v)
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return os.path.join(xdg, "linelore")
    return os.path.join(os.path.expanduser("~"), ".cache", "linelore")


class GitHub:
    def __init__(self, token=None, api="https://api.github.com", opener=None, cache_dir=None):
        self.token = token
        self.api = api.rstrip("/")
        self._open = opener or urllib.request.urlopen
        self._mem = {}
        # cache_dir=False means caller forced off; None means resolve from env
        if cache_dir is False:
            self.cache_dir = None
        elif cache_dir is not None:
            self.cache_dir = cache_dir
        else:
            self.cache_dir = resolve_cache_dir()

    def _cache_key(self, method, path, body):
        host = self.api
        raw = "%s %s %s %s" % (host, method, path, json.dumps(body, sort_keys=True) if body is not None else "")
        return hashlib.sha256(raw.encode()).hexdigest()

    def _disk_path(self, key):
        if not self.cache_dir:
            return None
        return os.path.join(self.cache_dir, key[:2], key + ".json")

    def _mem_get(self, key):
        return self._mem.get(key)

    def _disk_get(self, key):
        path = self._disk_path(key)
        if not path or not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _store(self, key, value):
        self._mem[key] = value
        path = self._disk_path(key)
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(value, f)
            os.replace(tmp, path)
        except OSError:
            pass

    def clear_cache(self):
        self._mem.clear()

    def _req(self, method, path, body=None, use_cache=True):
        key = self._cache_key(method, path, body) if use_cache else None
        if key is not None:
            hit = self._mem_get(key)
            if hit is not None:
                return hit
            hit = self._disk_get(key)
            if hit is not None:
                self._mem[key] = hit
                return hit
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
                result = json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:200]
            if e.code in (403, 429) and "rate limit" in msg.lower():
                raise GitHubError("GitHub rate limit hit; set GH_TOKEN or run `gh auth login`")
            raise GitHubError("GitHub API %s %s -> %s %s" % (method, url, e.code, msg))
        except urllib.error.URLError as e:
            raise GitHubError("cannot reach GitHub: %s" % e.reason)
        if key is not None:
            self._store(key, result)
        return result

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
