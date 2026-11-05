"""Building review and approval bodies from findings. Pure functions, no I/O."""

from __future__ import annotations

import re

from .config import CONFIG


def commentable_lines(diff: str) -> dict[str, set[int]]:
    """RIGHT-side lines GitHub accepts inline comments on: added or context lines inside a hunk."""
    lines: dict[str, set[int]] = {}
    path, new = None, 0
    for raw in diff.splitlines():
        if raw.startswith("diff --git"):
            path = None
        elif raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif m := re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", raw):
            new = int(m.group(1))
        elif path and raw[:1] in (" ", "+"):
            lines.setdefault(path, set()).add(new)
            new += 1
    return lines


SEVERITY_WORDS = {"must-fix": "Must fix", "should-fix": "Should fix", "minor": "Small thing, optional"}
VERDICT_WORDS = {
    "addressed": "Fixed",
    "pushback_accepted": "OK, no change needed",
    "not_addressed": "Not fixed yet",
    "needs_human": "Needs a person to decide",
}
ORDINALS = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth", "Tenth"]


def header(round_no: int) -> str:
    """E.g. '**First round of review (with AI help):**'."""
    label = CONFIG["review_label"]
    if 0 < round_no <= len(ORDINALS):
        return f"**{ORDINALS[round_no - 1]} round of review ({label}):**"
    return f"**Review round {round_no} ({label}):**"


def comment_body(finding: dict) -> str:
    tag = SEVERITY_WORDS.get(finding["severity"], finding["severity"])
    if finding.get("pre_existing"):
        tag += ", was already there before this PR"
    return f"**{finding['title']}** _({tag})_\n\n{finding['body']}"


def reply_body(verdict: str, reply: str) -> str:
    return f"**{VERDICT_WORDS.get(verdict, verdict)}** _(checked {CONFIG['review_label']})_\n\n{reply}"


def review_summary(out: dict) -> str:
    """The review pass's summary, requirement checklist and release steps as one markdown body."""
    parts = [out["summary"]]
    if out.get("ticket_coverage"):
        lines = [f"*   **{c['requirement']}: {c['status'].rstrip('.')}.** {c['note']}" for c in out["ticket_coverage"]]
        parts.append("**Checking the requirements:**\n" + "\n".join(lines))
    if out.get("before_release", "").strip():
        parts.append(f"**Before we can release this:** {out['before_release'].strip()}")
    return "\n\n".join(parts)


def split_findings(findings: list[dict], diff: str) -> tuple[list[dict], list[dict]]:
    allowed = commentable_lines(diff)
    inline, outside = [], []
    for f in findings:
        (inline if f["line"] in allowed.get(f["path"], set()) else outside).append(f)
    return inline, outside


def review_payload(pr: dict, round_no: int, summary: str, inline: list[dict], outside: list[dict], extra: str = "") -> dict:
    body = [header(round_no), "", summary]
    if extra:
        body += ["", extra]
    if outside:
        body += ["", "**Comments on lines this PR didn't change:**"]
        body += [f"- `{f['path']}:{f['line']}`: {comment_body(f)}" for f in outside]
    body += ["", f"<!-- auto-review sha={pr['headRefOid']} round={round_no} -->"]
    return {
        "commit_id": pr["headRefOid"],
        "event": "COMMENT",
        "body": "\n".join(body),
        "comments": [{"path": f["path"], "line": f["line"], "side": "RIGHT", "body": comment_body(f)} for f in inline],
    }


def approval(pr: dict, round_no: int, summary: str) -> dict:
    body = f"{header(round_no)}\n\n{summary}\n\n<!-- auto-review sha={pr['headRefOid']} round={round_no} -->"
    return {"commit_id": pr["headRefOid"], "event": "APPROVE", "body": body}
