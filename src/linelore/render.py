import datetime
import json


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


def _commit_block(path, blame, pulls, notes, color, lines=None, heading_path=True):
    def c(code, s):
        return "\033[%sm%s\033[0m" % (code, s) if color else s
    out = []
    if heading_path:
        if lines is not None:
            out.append(c("1", "%s:%s" % (path, _format_lines(lines))) + "  " + (blame.get("content") or "").strip())
        else:
            out.append(c("1", "%s:%s" % (path, blame.get("line"))) + "  " + (blame.get("content") or "").strip())
    elif lines is not None:
        out.append(c("1", "lines %s" % _format_lines(lines)) + "  " + (blame.get("content") or "").strip())
    out.append("  commit  %s  %s  %s" % (c("33", blame["sha"][:10]), _date(blame.get("author_time")), blame.get("author", "?")))
    out.append("          %s" % blame.get("summary", ""))
    for pr in pulls:
        out.append("  " + c("32", "PR #%d" % pr["number"]) + "  %s  (@%s, merged %s)" % (pr["title"], pr["author"], _date(pr["merged_at"])))
        out.append("          %s" % pr["url"])
        if pr["body"]:
            out.append("          “%s”" % pr["body"])
        for i in pr["issues"]:
            label = "fixes #%d" % i["number"]
            title = i["title"] or ""
            state = (i["state"] or "").lower() if i.get("state") else ("mentioned" if i.get("promoted") else "")
            state_bit = " [%s]" % state if state else ""
            out.append("  " + c("35", label) + "  %s%s" % (title, state_bit))
            out.append("          %s" % i["url"])
        if pr["mentions"]:
            out.append("  mentions  " + ", ".join(pr["mentions"]))
        for rc in pr["review_comments"]:
            if rc.get("near", True):
                where = "line %s" % rc["line"]
            elif rc.get("line"):
                where = "elsewhere in this file, line %s at review time" % rc["line"]
            else:
                where = "elsewhere in this file, outdated diff"
            out.append("  " + c("36", "review") + "  @%s (%s): %s" % (rc["author"], where, rc["body"]))
    for n in notes:
        out.append("  note    " + n)
    return out


def to_text(lore, color=False):
    def c(code, s):
        return "\033[%sm%s\033[0m" % (code, s) if color else s
    commits = lore.get("commits")
    if commits and lore.get("range") and len(commits) >= 1:
        start, end = lore["range"]["start"], lore["range"]["end"]
        out = []
        out.append(c("1", "%s:%d–%d" % (lore["path"], start, end))
                   + "  (%d unique commit%s)" % (len(commits), "" if len(commits) == 1 else "s"))
        for i, block in enumerate(commits):
            if i:
                out.append("")
            out.extend(_commit_block(
                lore["path"], block["blame"], block["pulls"], block["notes"],
                color, lines=block.get("lines"), heading_path=False,
            ))
        for n in lore.get("notes") or []:
            out.append("  note    " + n)
        return "\n".join(out)
    b = lore["blame"]
    return "\n".join(_commit_block(lore["path"], b, lore["pulls"], lore["notes"], color))
