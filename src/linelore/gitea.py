"""Gitea / Forgejo (Codeberg and self-hosted) backend, REST v1."""
from .forge import CommitNotFound, Forge, ForgeError, TOKEN_VARS
from .lore import closing_refs


PAGE_LIMIT = 50        # Gitea's and Codeberg's default MAX_RESPONSE_ITEMS
MAX_REVIEW_PAGES = 10  # 500 reviews; a PR with more is a rare beast, and each page is a request
MAX_REVIEW_THREADS = 50  # reviews whose inline comments we fetch (one request each), newest first


def _state(pr):
    return "open" if pr.get("state") == "open" else "closed"


class Gitea(Forge):
    name = "gitea"
    token_vars = TOKEN_VARS["gitea"]
    # /commits/{sha}/pull only knows a PR's merge commit, so for "merge commit"
    # style repos lore asks git for the merge that brought the line in and retries.
    pr_by_merge_commit_only = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._pulls = {}

    def _headers(self):
        h = {"Accept": "application/json"}
        if self.token:
            h["Authorization"] = "token " + self.token
        return h

    def _norm(self, pr):
        return {
            "number": pr.get("number"),
            "title": pr.get("title"),
            "html_url": pr.get("html_url"),
            "user": {"login": (pr.get("user") or {}).get("login")},
            "merged_at": pr.get("merged_at") if pr.get("merged", pr.get("merged_at") is not None) else None,
            "state": _state(pr),
            "body": pr.get("body") or "",
        }

    def _repo_missing(self, owner, repo):
        hint = "set %s" % self.token_hint if not self.token else "check --repo OWNER/REPO"
        return ForgeError("%s/%s not found on %s (private? %s)" % (owner, repo, self.host, hint))

    def commit_pulls(self, owner, repo, sha):
        path = "/repos/%s/%s/commits/%s/pull" % (owner, repo, sha)
        hit, val = self.cached("GET", path)
        if hit:
            pr = val
        else:
            try:
                pr = self.get(path, use_cache=False)
            except ForgeError as e:
                if getattr(e, "status", None) != 404:
                    raise
                # 404 means "no PR" — or no such repo, or no such commit. Tell them apart,
                # uncached: right after a push (or a new token) the answer must be today's.
                if self.get("/repos/%s/%s" % (owner, repo), missing={}, use_cache=False) == {}:
                    raise self._repo_missing(owner, repo)
                if self.get("/repos/%s/%s/git/commits/%s" % (owner, repo, sha), missing={}, use_cache=False) == {}:
                    raise CommitNotFound("commit %s isn't on %s/%s/%s (not pushed yet?)" % (sha[:10], self.host, owner, repo))
                pr = {}
            self.remember("GET", path, pr)
        if not pr:
            return []
        out = self._norm(pr)
        self._pulls[(owner, repo, out["number"])] = pr
        return [out]

    def _pull(self, owner, repo, number):
        pr = self._pulls.get((owner, repo, number))
        if pr is None:
            pr = self.get("/repos/%s/%s/pulls/%d" % (owner, repo, number)) or {}
            self._pulls[(owner, repo, number)] = pr
        return pr

    def closing_issues(self, owner, repo, number):
        """Gitea has no "closes" API: read Fixes/Closes/Resolves refs from the PR and look each issue up."""
        pr = self._pull(owner, repo, number)
        text = "%s\n%s" % (pr.get("title") or "", pr.get("body") or "")
        out = []
        for full, n in closing_refs(text, owner, repo)[:10]:
            issue = self.get("/repos/%s/issues/%d" % (full, n), missing={})
            if not issue:
                continue  # lore promotes it as a plain mention-style fix
            out.append({"number": n, "title": issue.get("title"), "url": issue.get("html_url"),
                        "state": "CLOSED" if issue.get("state") == "closed" else "OPEN",
                        "body": issue.get("body") or ""})
        return out

    def _reviews(self, owner, repo, number):
        """A PR's reviews, oldest first (Gitea's order), up to MAX_REVIEW_PAGES pages.

        Returns (reviews, cut, total): cut is True when there were more pages than
        we read; total is the server's X-Total-Count when it sent one.
        /pulls/N/reviews pages with ?limit=&page= and sends X-Total-Count (some
        versions also send Link). Page URLs are built here rather than taken from
        Link, so a server with a wrong ROOT_URL can't send the token elsewhere.
        The whole list is cached as one answer; a cut-short one is stored as
        {"reviews": [...], "total": N} so its note survives a cache hit.
        """
        base = "/repos/%s/%s/pulls/%d/reviews" % (owner, repo, number)
        key = "%s?limit=%d&page=all" % (base, PAGE_LIMIT)
        hit, val = self.cached("GET", key)
        if hit:
            if isinstance(val, dict):
                return val.get("reviews") or [], True, val.get("total")
            return val, False, None
        reviews, seen, total, cut = [], set(), None, False
        for page in range(1, MAX_REVIEW_PAGES + 1):
            items, headers = self.get("%s?limit=%d&page=%d" % (base, PAGE_LIMIT, page), with_headers=True)
            fresh = [r for r in (items if isinstance(items, list) else []) if isinstance(r, dict) and r.get("id") not in seen]
            if not fresh:
                break  # past the end, or a server that ignores ?page= and repeats itself
            seen.update(r.get("id") for r in fresh)
            reviews.extend(fresh)
            try:
                total = int(headers.get("x-total-count"))
            except (TypeError, ValueError):
                total = None
            if "link" in headers:
                more = 'rel="next"' in headers["link"]
            elif total is not None:
                more = len(reviews) < total  # pending reviews of others count but are hidden: an empty page ends it
            else:
                more = True  # no paging headers at all: read until an empty page
            if not more:
                break
            cut = page == MAX_REVIEW_PAGES
        self.remember("GET", key, {"reviews": reviews, "total": total} if cut else reviews)
        return reviews, cut, total

    def pull_review_comments(self, owner, repo, number):
        reviews, cut, total = self._reviews(owner, repo, number)
        if cut:
            self.notice("PR #%d has %s reviews; only the first %d were read for review comments"
                        % (number, total if total and total > len(reviews) else "more than %d" % len(reviews),
                           len(reviews)))
        threads = [r for r in reviews if r.get("comments_count") and r.get("id")]
        if len(threads) > MAX_REVIEW_THREADS:
            self.notice("PR #%d has %d reviews with inline comments; only the newest %d were read"
                        % (number, len(threads), MAX_REVIEW_THREADS))
            threads = threads[-MAX_REVIEW_THREADS:]
        out = []
        for r in threads:
            # one review's comments come back in one response (this endpoint doesn't page)
            for c in self.get("/repos/%s/%s/pulls/%d/reviews/%d/comments" % (owner, repo, number, r["id"])) or []:
                # Gitea's position / original_position are new-side / old-side line numbers
                out.append({
                    "path": c.get("path"),
                    "line": c.get("position") or None,
                    "original_line": c.get("original_position") or None,
                    "body": c.get("body") or "",
                    "user": {"login": (c.get("user") or {}).get("login")},
                    "html_url": c.get("html_url"),
                })
        return out
