"""Assemble the story behind a line."""
import re

ISSUE_REF = re.compile(r"(?<![\w/])(?:([\w.-]+/[\w.-]+))?#(\d+)\b")


def excerpt(text, limit=280):
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def issue_refs(text, owner, repo):
    refs = []
    for m in ISSUE_REF.finditer(text or ""):
        full = m.group(1) or "%s/%s" % (owner, repo)
        key = (full, int(m.group(2)))
        if key not in refs:
            refs.append(key)
    return refs


def comments_for(comments, path, line_hint=None, window=6):
    """Review comments on `path`, nearest to the line first when we know it.

    Returns (comments, near): `near` is False when nothing fell within `window`
    lines and we fell back to every comment on the file."""
    out = [c for c in comments if c.get("path") == path]
    def dist(c):
        ln = c.get("line") or c.get("original_line")
        return abs(ln - line_hint) if (ln and line_hint) else 10 ** 6
    out.sort(key=dist)
    if line_hint:
        near = [c for c in out if dist(c) <= window]
        if near:
            return near, True
    return out, False


def build_lore(blame, owner, repo, gh, path, max_comments=5):
    """Return a dict describing commit -> PR -> issues -> review comments."""
    lore = {"repo": "%s/%s" % (owner, repo) if owner else None, "path": path, "blame": blame,
            "pulls": [], "notes": []}
    if blame.get("uncommitted"):
        lore["notes"].append("line is not committed yet")
        return lore
    if gh is None:
        lore["notes"].append("offline: showing local commit only")
        return lore
    if not owner:
        lore["notes"].append("no GitHub remote; showing local commit only")
        return lore
    pulls = gh.commit_pulls(owner, repo, blame["sha"])
    if not pulls:
        lore["notes"].append("no pull request found for this commit (pushed directly?)")
    for pr in pulls[:3]:
        num = pr["number"]
        entry = {"number": num, "title": pr.get("title"), "url": pr.get("html_url"),
                 "author": (pr.get("user") or {}).get("login"), "merged_at": pr.get("merged_at"),
                 "state": pr.get("state"), "body": excerpt(pr.get("body"))}
        issues = gh.closing_issues(owner, repo, num)
        entry["issues"] = [{"number": i["number"], "title": i["title"], "url": i["url"],
                            "state": i.get("state"), "body": excerpt(i.get("body"), 200)} for i in issues]
        known = {i["number"] for i in issues}
        entry["mentions"] = ["%s#%d" % r for r in issue_refs(pr.get("body"), owner, repo)
                             if not (r[0] == "%s/%s" % (owner, repo) and r[1] in known)]
        line_hint = blame.get("orig_line")
        cs, near = comments_for(gh.pull_review_comments(owner, repo, num), blame.get("filename", path), line_hint)
        entry["review_comments"] = [{"author": (c.get("user") or {}).get("login"), "url": c.get("html_url"),
                                     "line": c.get("line") or c.get("original_line"),
                                     "body": excerpt(c.get("body"), 240), "near": near} for c in cs[:max_comments]]
        lore["pulls"].append(entry)
    return lore
