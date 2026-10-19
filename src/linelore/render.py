import datetime
import json
import re
import textwrap

from .forge import change_noun


def _date(ts):
    if not ts:
        return "?"
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d") if isinstance(ts, int) else str(ts)[:10]


def _format_lines(lines):
    """Compact line list: 10–12, 15, 20–22."""
    if not lines:
        return "?"
    lines = sorted(lines)
    parts = []
    run_start = run_end = lines[0]
    for n in lines[1:]:
        if n == run_end + 1:
            run_end = n
        else:
            parts.append("%d–%d" % (run_start, run_end) if run_start != run_end else str(run_start))
            run_start = run_end = n
    parts.append("%d–%d" % (run_start, run_end) if run_start != run_end else str(run_start))
    return ", ".join(parts)


def to_json(lore):
    return json.dumps(lore, indent=2, ensure_ascii=False)


def _status(pr):
    """"merged 2024-05-24", "open", "closed without merging"."""
    if pr.get("merged_at"):
        return "merged %s" % _date(pr["merged_at"])
    if pr.get("state") == "open":
        return "still open"
    return "closed without merging" if pr.get("state") == "closed" else "state unknown"


def _wrap(text, width, indent):
    """Wrap to the terminal when we know its width; one line otherwise (pipes, grep)."""
    if not width or width - indent < 30:
        return [text]
    return textwrap.wrap(text, width - indent, break_long_words=False, break_on_hyphens=False) or [text]


def _commit_block(path, blame, pulls, notes, color, lines=None, heading_path=True, forge=None, width=None,
                  seen=None):
    def c(code, s):
        return "\033[%sm%s\033[0m" % (code, s) if color else s
    pad = " " * 10
    noun, sigil, _ = change_noun(forge)
    out = []
    if heading_path:
        if lines is not None:
            out.append(c("1", "%s:%s" % (path, _format_lines(lines))) + "  " + (blame.get("content") or "").strip())
        else:
            out.append(c("1", "%s:%s" % (path, blame.get("line"))) + "  " + (blame.get("content") or "").strip())
    elif lines is not None:
        out.append(c("1", "lines %s" % _format_lines(lines)) + "  " + (blame.get("content") or "").strip())
    out.append("  commit  %s  %s  %s" % (c("33", blame["sha"][:10]), _date(blame.get("author_time")), blame.get("author", "?")))
    out.append(pad + "%s" % blame.get("summary", ""))
    for pr in pulls:
        who = "@%s, " % pr["author"] if pr.get("author") else ""
        label = c("32", "%s %s%d" % (noun, sigil, pr["number"]))
        if seen is not None and pr["number"] in seen:
            # same PR as an earlier commit in this range: don't repeat its story
            out.append("  " + label + "  %s  (same %s as above)" % (pr["title"], noun))
            continue
        if seen is not None:
            seen.add(pr["number"])
        out.append("  " + label + "  %s  (%s%s)" % (pr["title"], who, _status(pr)))
        if pr.get("url"):
            out.append(pad + c("2", pr["url"]))
        if pr["body"]:
            body = _wrap("“%s”" % pr["body"], width, 10)
            out.extend(pad + ln for ln in body)
        for i in pr["issues"]:
            label = "fixes #%d" % i["number"]
            title = i["title"] or ""
            state = (i["state"] or "").lower() if i.get("state") else ("mentioned" if i.get("promoted") else "")
            state_bit = " [%s]" % state if state else ""
            out.append("  " + c("35", label) + "  %s%s" % (title, state_bit))
            if i.get("url"):
                out.append(pad + c("2", i["url"]))
        if pr["mentions"]:
            out.append("  mentions  " + ", ".join(pr["mentions"]))
        for rc in pr["review_comments"]:
            if rc.get("near", True):
                where = "line %s" % rc["line"]
            elif rc.get("line"):
                where = "elsewhere in this file, line %s at review time" % rc["line"]
            else:
                where = "elsewhere in this file, outdated diff"
            head = "  " + c("36", "review") + "  @%s (%s): " % (rc["author"], where)
            body = _wrap(rc["body"], width, 10)
            out.append(head + body[0] if len(body) == 1 else head.rstrip())
            if len(body) > 1:
                out.extend(pad + ln for ln in body)
    for n in notes:
        out.append("  " + c("2", "note") + "    " + n)
    return out


def to_text(lore, color=False, width=None):
    def c(code, s):
        return "\033[%sm%s\033[0m" % (code, s) if color else s
    forge = lore.get("forge")
    commits = lore.get("commits")
    if commits and lore.get("range") and len(commits) >= 1:
        start, end = lore["range"]["start"], lore["range"]["end"]
        out = []
        out.append(c("1", "%s:%d–%d" % (lore["path"], start, end))
                   + "  (%d unique commit%s)" % (len(commits), "" if len(commits) == 1 else "s"))
        seen = set()
        for i, block in enumerate(commits):
            if i:
                out.append("")
            out.extend(_commit_block(
                lore["path"], block["blame"], block["pulls"], block["notes"],
                color, lines=block.get("lines"), heading_path=False, forge=forge, width=width, seen=seen,
            ))
        for n in lore.get("notes") or []:
            if re.match(r"\d+ unique commits in lines", n):
                continue  # already in the heading
            out.append("  " + c("2", "note") + "    " + n)
        return "\n".join(out)
    b = lore["blame"]
    return "\n".join(_commit_block(lore["path"], b, lore["pulls"], lore["notes"], color, forge=forge, width=width))
