"""Forge abstraction: HTTP + cache shared by the GitHub, GitLab and Gitea backends.

Every backend answers the same three questions for lore.build_lore and returns
the same dict shapes, whatever the forge calls things:

  commit_pulls(owner, repo, sha) -> [change]
      change = {number, title, html_url, user: {login}, merged_at, state, body}
      (`number` is the GitLab MR iid; `state` is "open" or "closed", with
      merged_at set when it was merged)
  closing_issues(owner, repo, number) -> [{number, title, url, state, body}]
      (state "OPEN" / "CLOSED")
  pull_review_comments(owner, repo, number) -> [comment]
      comment = {path, line, original_line, body, user: {login}, html_url}

`owner/repo` is the full project path; on GitLab `repo` may contain slashes
(group/subgroup/project). Responses are cached in memory for the process and on
disk (see resolve_cache_dir), keyed by forge + API host + request, so the same
commit sha is looked up once per forge. Empty answers ("no PR for this commit
yet", "no review comments yet", a 404 turned into `missing`) only stay valid on
disk for empty_ttl() seconds, because they are the ones that change.
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

FORGES = ("github", "gitlab", "gitea")

# Hosts we recognise without asking. Everything else needs --forge (or a host
# name that says what it is, like gitlab.example.com).
KNOWN_HOSTS = {
    "github.com": "github",
    "ssh.github.com": "github",
    "gitlab.com": "gitlab",
    "altssh.gitlab.com": "gitlab",
    "salsa.debian.org": "gitlab",
    "gitlab.gnome.org": "gitlab",
    "gitlab.freedesktop.org": "gitlab",
    "invent.kde.org": "gitlab",
    "framagit.org": "gitlab",
    "gitlab.archlinux.org": "gitlab",
    "codeberg.org": "gitea",
    "gitea.com": "gitea",
    "code.forgejo.org": "gitea",
}
# Canonical web/API host for ssh-only aliases of the big hosted forges.
SSH_ALIASES = {"ssh.github.com": "github.com", "altssh.gitlab.com": "gitlab.com"}
FORGEJO_HOSTS = {"codeberg.org", "code.forgejo.org"}

TITLES = {"github": "GitHub", "gitlab": "GitLab", "gitea": "Gitea"}
# What each forge calls a change request, and how it is referenced in text.
CHANGE_NOUN = {"github": ("PR", "#", "pull request"),
               "gitlab": ("MR", "!", "merge request"),
               "gitea": ("PR", "#", "pull request")}
TOKEN_VARS = {"github": ("LINELORE_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"),
              "gitlab": ("GITLAB_TOKEN",),
              "gitea": ("GITEA_TOKEN", "FORGEJO_TOKEN")}


class ForgeError(RuntimeError):
    """A forge lookup failed; the message is meant for the user."""


class CommitNotFound(ForgeError):
    """The forge does not know this commit (usually: not pushed yet)."""


class Unauthorized(ForgeError):
    """401: the endpoint needs a (valid) token."""


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


EMPTY_TTL = 3600  # seconds an empty answer stays valid on disk (LINELORE_CACHE_EMPTY_TTL)


def empty_ttl():
    """Seconds an empty answer ("no PR for this commit") stays valid on disk.

    LINELORE_CACHE_EMPTY_TTL overrides the one-hour default; 0 keeps empty
    answers out of the disk cache entirely. Anything unparsable means the default.
    """
    raw = os.environ.get("LINELORE_CACHE_EMPTY_TTL")
    if raw is None or not raw.strip():
        return EMPTY_TTL
    try:
        return max(0.0, float(raw))
    except ValueError:
        return EMPTY_TTL


def is_empty_answer(value):
    """[] or {}: the forge said "nothing (yet)". Those can change; real answers rarely do."""
    return isinstance(value, (list, dict)) and not value


def describe_age(seconds):
    """'just now', '1 min ago', '42 min ago', '3 h ago'."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "just now"
    if minutes < 120:
        return "%d min ago" % minutes
    return "%d h ago" % (minutes // 60)


def change_noun(forge):
    """("PR", "#", "pull request") or ("MR", "!", "merge request")."""
    return CHANGE_NOUN.get(forge or "github", CHANGE_NOUN["github"])


def forge_title(forge, host=None):
    if forge == "gitea" and host in FORGEJO_HOSTS:
        return "Forgejo"
    return TITLES.get(forge or "github", "GitHub")


# --------------------------------------------------------------------------
# detection
# --------------------------------------------------------------------------

class UnknownForge(ForgeError):
    pass


class ForgeSpec:
    """Which forge, where its API lives, and its web base (for links)."""

    def __init__(self, name, api, web, host=None):
        self.name, self.api, self.web, self.host = name, api.rstrip("/"), web.rstrip("/"), host

    @property
    def title(self):
        return forge_title(self.name, urllib.parse.urlparse(self.web).hostname)

    def commit_url(self, full, sha):
        sep = "/-/" if self.name == "gitlab" else "/"
        return "%s/%s%scommit/%s" % (self.web, full, sep, sha)

    def __repr__(self):
        return "ForgeSpec(%r, %r, %r)" % (self.name, self.api, self.web)

    def __eq__(self, other):
        return isinstance(other, ForgeSpec) and (self.name, self.api, self.web) == (other.name, other.api, other.web)


def _canon_host(host):
    if not host:
        return None
    host = host.lower()
    if "." not in host:  # ~/.ssh/config alias such as "github-work" or "gitlab"
        for word, real in (("github", "github.com"), ("gitlab", "gitlab.com"), ("codeberg", "codeberg.org")):
            if word in host:
                return real
        return host
    return SSH_ALIASES.get(host, host)


def forge_for_host(host):
    """Best guess from the host name alone, or None."""
    host = _canon_host(host)
    if not host:
        return None
    if host in KNOWN_HOSTS:
        return KNOWN_HOSTS[host]
    labels = re.split(r"[.-]", host)
    for word, name in (("gitlab", "gitlab"), ("gitea", "gitea"), ("forgejo", "gitea"), ("github", "github")):
        if word in labels:
            return name
    return None


def forge_for_api(api):
    path = urllib.parse.urlparse(api).path.rstrip("/")
    if path.endswith("/api/v4"):
        return "gitlab"
    if path.endswith("/api/v1"):
        return "gitea"
    return "github"


def default_api(name, host):
    if name == "github":
        return "https://api.github.com" if host in (None, "github.com") else "https://%s/api/v3" % host
    if name == "gitlab":
        return "https://%s/api/v4" % (host or "gitlab.com")
    return "https://%s/api/v1" % (host or "codeberg.org")


def web_from_api(name, api):
    u = urllib.parse.urlparse(api)
    if u.hostname == "api.github.com":
        return "https://github.com"
    path = re.sub(r"/api(?:/v[134])?/?$", "", u.path.rstrip("/"))
    return "%s://%s%s" % (u.scheme or "https", u.netloc, path)


def resolve_forge(host, forge=None, api=None, env_api=None):
    """Pick the forge for a remote host.

    Order: --forge, then --api's shape (/api/v4 = GitLab, /api/v1 = Gitea,
    anything else GitHub), then the host name, then LINELORE_API (a GitHub
    Enterprise setting). Raises UnknownForge when there is nothing to go on.
    """
    host = _canon_host(host)
    if forge == "forgejo":
        forge = "gitea"
    name = forge or (forge_for_api(api) if api else None) or forge_for_host(host)
    if not name:
        if env_api:
            name = "github"
        elif host is None:
            name = "github"  # --repo without a parseable remote: v0.2 behaviour
        else:
            raise UnknownForge(
                "can't tell which forge %s runs; pass --forge gitlab, --forge gitea or --forge github "
                "(plus --api URL if its API isn't at https://%s/api/...)" % (host, host))
    if not api and name == "github" and env_api:
        api = env_api
    api = (api or default_api(name, host)).rstrip("/")
    return ForgeSpec(name, api, web_from_api(name, api), host)


# --------------------------------------------------------------------------
# HTTP + cache
# --------------------------------------------------------------------------

class Forge:
    name = "github"
    token_vars = TOKEN_VARS["github"]
    clock = staticmethod(time.time)  # tests swap this to move time forward

    def __init__(self, token=None, api=None, opener=None, cache_dir=None, web=None):
        self.token = token
        self.api = (api or default_api(self.name, None)).rstrip("/")
        self.web = (web or web_from_api(self.name, self.api)).rstrip("/")
        self.host = urllib.parse.urlparse(self.api).hostname or self.api
        self._open = opener or urllib.request.urlopen
        try:
            self.timeout = float(os.environ.get("LINELORE_TIMEOUT") or 30)
        except ValueError:
            self.timeout = 30.0
        self._mem = {}
        self.empty_ttl = empty_ttl()
        self._empty_age = None  # oldest empty answer served from disk; see pop_cached_empty_age
        self._notices = []
        # cache_dir=False means caller forced off; None means resolve from env
        if cache_dir is False:
            self.cache_dir = None
        elif cache_dir is not None:
            self.cache_dir = cache_dir
        else:
            self.cache_dir = resolve_cache_dir()

    # -- naming -----------------------------------------------------------
    @property
    def title(self):
        return forge_title(self.name, urllib.parse.urlparse(self.web).hostname)

    @property
    def token_hint(self):
        if self.name == "github":
            return "GH_TOKEN"
        if self.name == "gitea" and self.title == "Forgejo":
            return "FORGEJO_TOKEN"
        return self.token_vars[0]

    def issue_url(self, full, number):
        return "%s/%s/issues/%d" % (self.web, full, number)

    # -- cache ------------------------------------------------------------
    def _cache_key(self, method, path, body):
        raw = "%s %s %s %s %s" % (self.name, self.api, method, path,
                                  json.dumps(body, sort_keys=True) if body is not None else "")
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
                value = json.load(f)
            age = self.clock() - os.path.getmtime(path)
        except (OSError, json.JSONDecodeError):
            return None
        if is_empty_answer(value):
            # "nothing yet" goes stale: the PR gets opened, reviews come in. An mtime
            # well in the future (the clock moved back) counts as stale too; a few
            # seconds of skew (coarse clocks, network file systems) does not.
            if age < -60 or age >= self.empty_ttl:
                return None
            self._empty_age = max(age, self._empty_age or 0, 0)
        return value

    def _store(self, key, value):
        self._mem[key] = value
        path = self._disk_path(key)
        if not path or (is_empty_answer(value) and self.empty_ttl <= 0):
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(value, f)
            os.replace(tmp, path)  # fresh mtime: the TTL of an empty answer counts from here
        except OSError:
            pass

    def notice(self, text):
        """Something the reader should know about this lookup (e.g. a list was cut short)."""
        if text not in self._notices:
            self._notices.append(text)

    def pop_notices(self):
        """Notices since the last call; lore turns them into notes."""
        out, self._notices = self._notices, []
        return out

    def pop_cached_empty_age(self):
        """Age in seconds of the oldest empty answer read from the disk cache since
        the last call (None if there was none), so "no PR" can say it was cached."""
        age, self._empty_age = self._empty_age, None
        return age

    def clear_cache(self):
        self._mem.clear()

    def cached(self, method, path, body=None):
        """(hit, value) without touching the network."""
        key = self._cache_key(method, path, body)
        hit = self._mem_get(key)
        if hit is None:
            hit = self._disk_get(key)
            if hit is not None:
                self._mem[key] = hit
        return hit is not None, hit

    def remember(self, method, path, value, body=None):
        self._store(self._cache_key(method, path, body), value)

    # -- HTTP -------------------------------------------------------------
    def _headers(self):
        return {}

    def _http_error(self, method, url, code, msg, headers):
        """Turn an HTTP error into a ForgeError a person can act on."""
        low = msg.lower()
        remaining = (headers.get("X-RateLimit-Remaining") or headers.get("RateLimit-Remaining") or "") if headers else ""
        if code == 429 or (code == 403 and ("rate limit" in low or remaining == "0")):
            hint = ("set %s" % self.token_hint) if not self.token else "wait a little and retry (cached lookups stay free)"
            if self.name == "github" and not self.token:
                hint = "set GH_TOKEN or run `gh auth login`"
            return ForgeError("%s rate limit hit on %s; %s" % (self.title, self.host, hint))
        if code == 401:
            if self.token:
                return Unauthorized("%s rejected the token (401 on %s); check %s" % (self.title, self.host, self.token_hint))
            return Unauthorized("%s only shows these to signed-in users; set %s" % (self.host, self.token_hint))
        detail = ""
        try:
            j = json.loads(msg)
            detail = j.get("message") or j.get("error") or ""
            if isinstance(detail, dict):
                detail = json.dumps(detail)
        except (ValueError, AttributeError):
            detail = re.sub(r"\s+", " ", msg)[:160]
        return ForgeError("%s API %s %s -> %s %s" % (self.title, method, url, code, detail))

    def _req(self, method, path, body=None, use_cache=True, missing=None, with_headers=False):
        """JSON request. `missing` (if given) is returned for a 404 instead of raising
        and is cached like any other empty answer (so it expires after empty_ttl).
        with_headers=True returns (result, {lower-cased header: value}) and bypasses
        the cache, which doesn't keep headers (used for paging)."""
        if with_headers:
            use_cache = False
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
        req.add_header("User-Agent", "linelore")
        for k, v in self._headers().items():
            req.add_header(k, v)
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with self._open(req, timeout=self.timeout) as r:
                raw = r.read().decode("utf-8", errors="replace")
                hdrs = getattr(r, "headers", None)
                headers = {k.lower(): v for k, v in hdrs.items()} if hdrs else {}
        except urllib.error.HTTPError as e:
            msg = ""
            try:
                msg = e.read().decode(errors="replace")[:400]
            except Exception:
                pass
            if e.code == 404 and missing is not None:
                if key is not None:
                    self._store(key, missing)
                return (missing, {}) if with_headers else missing
            err = self._http_error(method, url, e.code, msg, e.headers)
            err.status = e.code
            err.body = msg
            raise err
        except urllib.error.URLError as e:
            raise ForgeError("cannot reach %s (%s): %s" % (self.title, self.host, e.reason))
        except (OSError, ValueError) as e:  # timeouts, resets
            if "timed out" in str(e).lower():
                raise ForgeError("%s (%s) did not answer within %gs; retry, or raise LINELORE_TIMEOUT"
                                 % (self.title, self.host, self.timeout))
            raise ForgeError("cannot reach %s (%s): %s" % (self.title, self.host, e))
        try:
            result = json.loads(raw or "null")
        except ValueError:
            raise ForgeError("%s did not answer with JSON; is the API URL right? (expected something like %s)"
                             % (url, default_api(self.name, self.host)))
        if key is not None:
            self._store(key, result)
        return (result, headers) if with_headers else result

    def get(self, path, **kw):
        return self._req("GET", path, **kw)

    # -- the three questions (subclasses) ---------------------------------
    def commit_pulls(self, owner, repo, sha):
        raise NotImplementedError

    def closing_issues(self, owner, repo, number):
        return []

    def pull_review_comments(self, owner, repo, number):
        return []


def find_env_token(name):
    for var in TOKEN_VARS.get(name, ()):
        if os.environ.get(var):
            return os.environ[var]
    return None


def make_forge(spec, opener=None, cache_dir=None, token=None):
    """Instantiate the backend for a ForgeSpec with the right token."""
    if spec.name == "gitlab":
        from .gitlab import GitLab as cls
    elif spec.name == "gitea":
        from .gitea import Gitea as cls
    else:
        from .github import GitHub as cls
    if token is None:
        if spec.name == "github":
            from .github import find_token
            token = find_token(urllib.parse.urlparse(spec.web).hostname)
        else:
            token = find_env_token(spec.name)
    return cls(token, api=spec.api, opener=opener, cache_dir=cache_dir, web=spec.web)
