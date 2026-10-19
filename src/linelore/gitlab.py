"""GitLab (gitlab.com and self-managed) backend, REST v4."""
import urllib.parse

from .forge import CommitNotFound, Forge, ForgeError, TOKEN_VARS


def _state(s):
    # GitLab: opened / merged / closed / locked -> the shared open/closed shape
    return "open" if s in ("opened", "open", "locked") else "closed"


class GitLab(Forge):
    name = "gitlab"
    token_vars = TOKEN_VARS["gitlab"]

    def _headers(self):
        return {"PRIVATE-TOKEN": self.token} if self.token else {}

    def issue_url(self, full, number):
        return "%s/%s/-/issues/%d" % (self.web, full, number)

    @staticmethod
    def project(owner, repo):
        return urllib.parse.quote("%s/%s" % (owner, repo), safe="")

    def _not_found(self, e, owner, repo, sha=None):
        body = (getattr(e, "body", "") or "").lower()
        if sha and "commit" in body:
            return CommitNotFound("commit %s isn't on %s/%s/%s (not pushed yet?)" % (sha[:10], self.host, owner, repo))
        hint = "set GITLAB_TOKEN" if not self.token else "check the project path or pass --repo GROUP/PROJECT"
        return ForgeError("%s/%s not found on %s (private? %s)" % (owner, repo, self.host, hint))

    def commit_pulls(self, owner, repo, sha):
        try:
            mrs = self.get("/projects/%s/repository/commits/%s/merge_requests" % (self.project(owner, repo), sha)) or []
        except ForgeError as e:
            if getattr(e, "status", None) == 404:
                raise self._not_found(e, owner, repo, sha)
            raise
        # merged first (that's the one that put the line on the default branch), then newest
        mrs = sorted(mrs, key=lambda m: (m.get("merged_at") is None, -(m.get("iid") or 0)))
        return [{
            "number": m.get("iid"),
            "title": m.get("title"),
            "html_url": m.get("web_url"),
            "user": {"login": (m.get("author") or {}).get("username")},
            "merged_at": m.get("merged_at"),
            "state": _state(m.get("state")),
            "body": m.get("description") or "",
        } for m in mrs]

    def closing_issues(self, owner, repo, number):
        res = self.get("/projects/%s/merge_requests/%d/closes_issues?per_page=20" % (self.project(owner, repo), number)) or []
        out = []
        for i in res:
            if not isinstance(i, dict) or "iid" not in i:
                continue  # external trackers (Jira) return a different shape
            out.append({"number": i["iid"], "title": i.get("title"), "url": i.get("web_url"),
                        "state": "CLOSED" if i.get("state") == "closed" else "OPEN",
                        "body": i.get("description") or ""})
        return out

    def pull_review_comments(self, owner, repo, number):
        """Diff notes (inline review comments, including replies in their thread)."""
        res = self.get("/projects/%s/merge_requests/%d/discussions?per_page=100" % (self.project(owner, repo), number)) or []
        out = []
        for d in res:
            for n in d.get("notes") or []:
                pos = n.get("position") or {}
                if n.get("system") or n.get("type") != "DiffNote" or not pos:
                    continue
                path = pos.get("new_path") or pos.get("old_path")
                mr_url = (n.get("noteable_url") or "")
                out.append({
                    "path": path,
                    "line": pos.get("new_line"),
                    "original_line": pos.get("old_line"),
                    "body": n.get("body") or "",
                    "user": {"login": (n.get("author") or {}).get("username")},
                    "html_url": ("%s#note_%s" % (mr_url, n["id"])) if mr_url and n.get("id")
                                else "%s/%s/%s/-/merge_requests/%d#note_%s" % (self.web, owner, repo, number, n.get("id")),
                })
        return out
