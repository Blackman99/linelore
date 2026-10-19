"""Assemble the story behind a line (or a range of lines)."""
import re

from .forge import CommitNotFound, Unauthorized, change_noun, describe_age, forge_title

# "#12", "owner/repo#3", GitLab "group/sub/project#4"
ISSUE_REF = re.compile(r"(?<![\w/])(?:([\w.-]+(?:/[\w.-]+)+))?#(\d+)\b")
_CLOSE_WORD = r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+"
# "Fixes #12", "Closes owner/repo#3", "Resolved #7", etc.
CLOSING_REF = re.compile(_CLOSE_WORD + r"(?:([\w.-]+(?:/[\w.-]+)+))?#(\d+)\b")
# "Fixes https://codeberg.org/o/r/issues/7", "Closes https://gitlab.com/g/p/-/issues/3"
CLOSING_URL = re.compile(_CLOSE_WORD + r"https?://[^/\s]+/([\w.-]+(?:/[\w.-]+)+?)/(?:-/)?issues/(\d+)\b")


_TRAILER = re.compile(r"(?im)^\s*(?:signed-off-by|co-authored-by|reviewed-by|acked-by|tested-by|"
                      r"approved-by|merged-by|change-id):.*$")
_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s+.*$")       # "## Description" template headings
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://|/)[^)\s]*\)")   # [text](url) -> text


def excerpt(text, limit=280):
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
    text = _TRAILER.sub("", text)
    text = _HEADING.sub("", text)
    text = _IMAGE.sub("", text)
    text = _LINK.sub(r"\1", text)
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


def closing_refs(text, owner, repo):
    """Issue refs introduced with Fixes/Closes/Resolves keywords."""
    found = []
    for rx in (CLOSING_REF, CLOSING_URL):
        for m in rx.finditer(text or ""):
            full = m.group(1) or "%s/%s" % (owner, repo)
            found.append((m.start(), (full, int(m.group(2)))))
    refs = []
    for _, key in sorted(found):
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



def _promote_closing_mentions(entry, pr, owner, repo, known, gh=None):
    """When GraphQL closingIssuesReferences is empty, promote Fixes/Closes/Resolves."""
    if entry["issues"]:
        return
    text = "%s\n%s" % (pr.get("title") or "", pr.get("body") or "")
    noun = change_noun(getattr(gh, "name", None))[0]
    promoted = []
    for full, num in closing_refs(text, owner, repo):
        if full == "%s/%s" % (owner, repo) and num in known:
            continue
        if any(i["number"] == num and i.get("_full") == full for i in promoted):
            continue
        promoted.append({
            "number": num,
            "title": "(mentioned in %s as Fixes/Closes/Resolves)" % noun,
            "url": gh.issue_url(full, num) if hasattr(gh, "issue_url") else "https://github.com/%s/issues/%d" % (full, num),
            "state": None,
            "body": "",
            "promoted": True,
            "_full": full,
        })
    if not promoted:
        return
    entry["issues"] = [{k: v for k, v in i.items() if k != "_full"} for i in promoted]
    # Drop promoted refs from mentions so they aren't listed twice
    promo_keys = {"%s#%d" % (i["_full"], i["number"]) for i in promoted}
    entry["mentions"] = [m for m in entry["mentions"] if m not in promo_keys]


def _add_note(lore, note):
    if note not in lore["notes"]:
        lore["notes"].append(note)


def _guarded(lore, what, fn, *args):
    """Call a forge endpoint that may need a token; degrade to [] with a note."""
    try:
        return fn(*args)
    except Unauthorized as e:
        _add_note(lore, "%s skipped: %s" % (what, e))
        return []


def build_lore(blame, owner, repo, gh, path, max_comments=5, line_hints=None, forge=None, merge_lookup=None,
               local_note="offline: showing local commit only"):
    """Return a dict describing commit -> PR/MR -> issues -> review comments.

    gh: a forge backend (see forge.py) or None for offline.
    forge: forge name for the JSON `forge` field (defaults to gh.name).
    line_hints: optional list of line numbers in the blamed range owned by this
    commit; used to pick nearby review comments (nearest to any of them).
    merge_lookup: optional sha -> merge-commit sha, for forges that only map a
    PR's merge commit to the PR (Gitea/Forgejo).
    local_note: the note shown when gh is None ("" for none).
    """
    forge = forge or getattr(gh, "name", None)
    title = getattr(gh, "title", None) or forge_title(forge)
    noun = change_noun(forge)
    lore = {"forge": forge, "repo": "%s/%s" % (owner, repo) if owner else None, "path": path, "blame": blame,
            "pulls": [], "notes": []}
    if blame.get("uncommitted"):
        lore["notes"].append("line is not committed yet")
        return lore
    if gh is None:
        if local_note:
            lore["notes"].append(local_note)
        return lore
    if not owner:
        lore["notes"].append("no %s remote; showing local commit only" % title)
        return lore
    cached_age = getattr(gh, "pop_cached_empty_age", lambda: None)
    cached_age()  # forget empty answers served for earlier lookups
    try:
        pulls = gh.commit_pulls(owner, repo, blame["sha"])
        if not pulls and merge_lookup and getattr(gh, "pr_by_merge_commit_only", False):
            merge = merge_lookup(blame["sha"])
            if merge and merge != blame["sha"]:
                pulls = gh.commit_pulls(owner, repo, merge)
    except CommitNotFound as e:
        lore["notes"].append(str(e))
        return lore
    if not pulls:
        note = "no %s found for this commit (pushed directly?)" % noun[2]
        age = cached_age()
        if age is not None:
            # a "no PR" from the disk cache may predate the PR; say so and how to re-ask
            note += "; cached %s (LINELORE_CACHE_EMPTY_TTL=0 to re-check)" % describe_age(age)
        lore["notes"].append(note)
    hints = line_hints or ([blame.get("orig_line")] if blame.get("orig_line") else [])
    hints = [h for h in hints if h]
    for pr in pulls[:3]:
        num = pr["number"]
        entry = {"number": num, "title": pr.get("title"), "url": pr.get("html_url"),
                 "author": (pr.get("user") or {}).get("login"), "merged_at": pr.get("merged_at"),
                 "state": pr.get("state"), "body": excerpt(pr.get("body"))}
        issues = _guarded(lore, "linked issues", gh.closing_issues, owner, repo, num)
        entry["issues"] = [{"number": i["number"], "title": i["title"], "url": i["url"],
                            "state": i.get("state"), "body": excerpt(i.get("body"), 200)} for i in issues]
        known = {i["number"] for i in issues}
        entry["mentions"] = ["%s#%d" % r for r in issue_refs(pr.get("body"), owner, repo)
                             if not (r[0] == "%s/%s" % (owner, repo) and r[1] in known)]
        _promote_closing_mentions(entry, pr, owner, repo, known, gh)
        # Prefer review comments near any of the owned lines (use first hint as primary)
        line_hint = hints[0] if hints else blame.get("orig_line")
        cs, near = comments_for(_guarded(lore, "review comments", gh.pull_review_comments, owner, repo, num),
                                blame.get("filename", path), line_hint)
        entry["review_comments"] = [{"author": (c.get("user") or {}).get("login"), "url": c.get("html_url"),
                                     "line": c.get("line") or c.get("original_line"),
                                     "body": excerpt(c.get("body"), 240), "near": near} for c in cs[:max_comments]]
        for n in getattr(gh, "pop_notices", list)():
            _add_note(lore, n)
        lore["pulls"].append(entry)
    return lore


def build_range_lore(groups, owner, repo, gh, path, start, end, forge=None, merge_lookup=None,
                     local_note="offline: showing local commit only"):
    """Build lore for a deduped list of {blame, lines} groups covering start-end."""
    forge = forge or getattr(gh, "name", None)
    commits = []
    for g in groups:
        entry = build_lore(g["blame"], owner, repo, gh, path, line_hints=g["lines"], forge=forge,
                           merge_lookup=merge_lookup, local_note=local_note)
        commits.append({
            "blame": entry["blame"],
            "lines": list(g["lines"]),
            "pulls": entry["pulls"],
            "notes": entry["notes"],
        })
    first = commits[0] if commits else None
    lore = {
        "forge": forge,
        "repo": "%s/%s" % (owner, repo) if owner else None,
        "path": path,
        "range": {"start": start, "end": end},
        "blame": first["blame"] if first else None,
        "pulls": first["pulls"] if first else [],
        "commits": commits,
        "notes": [],
    }
    if len(commits) > 1:
        lore["notes"].append("%d unique commits in lines %d–%d" % (len(commits), start, end))
    return lore
