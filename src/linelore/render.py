import datetime
import json


def _date(ts):
    if not ts:
        return "?"
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d") if isinstance(ts, int) else str(ts)[:10]


def to_json(lore):
    return json.dumps(lore, indent=2, ensure_ascii=False)


def to_text(lore, color=False):
    def c(code, s):
        return "\033[%sm%s\033[0m" % (code, s) if color else s
    b = lore["blame"]
    out = []
    out.append(c("1", "%s:%s" % (lore["path"], b.get("line"))) + "  " + (b.get("content") or "").strip())
    out.append("  commit  %s  %s  %s" % (c("33", b["sha"][:10]), _date(b.get("author_time")), b.get("author", "?")))
    out.append("          %s" % b.get("summary", ""))
    for pr in lore["pulls"]:
        out.append("  " + c("32", "PR #%d" % pr["number"]) + "  %s  (@%s, merged %s)" % (pr["title"], pr["author"], _date(pr["merged_at"])))
        out.append("          %s" % pr["url"])
        if pr["body"]:
            out.append("          “%s”" % pr["body"])
        for i in pr["issues"]:
            out.append("  " + c("35", "fixes #%d" % i["number"]) + "  %s [%s]" % (i["title"], (i["state"] or "").lower()))
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
    for n in lore["notes"]:
        out.append("  note    " + n)
    return "\n".join(out)
