"""`auto-review.py status`: a read-only overview of every PR the job has touched.

Reads state.json, the newest draft per PR and today's log. One GitHub search tells which PRs are
still waiting on me; nothing is posted and Claude is not run.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys

from . import config, github
from .config import CONFIG, HOME, LOCK_DIR, PAUSE_FILE, SETTLED
from .state import load_state

DRAFT_RE = re.compile(r"^(?P<owner>[^-]+)-(?P<repo>.+)-(?P<num>\d+)-(?P<sha>[0-9a-f]{8})-(?P<ts>\d+)\.json$")

# (group title, colour) in display order.
GROUPS = {
    "needs_you": ("Needs you", "31"),
    "error": ("Errors", "31"),
    "approved": ("Approved", "32"),
    "ready": ("Ready to approve (not posted)", "32"),
    "queued": ("Queued for the next run", "34"),
    "waiting_author": ("Waiting on the author", "33"),
    "waiting_checks": ("Concerns addressed, waiting on GitHub", "36"),
    "seen": ("Seen, nothing to do", "2"),
    "closed": ("No longer waiting on you (merged, closed or review not requested)", "2"),
}


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


def ago(ts: float | None) -> str:
    if not ts:
        return "-"
    mins = int((dt.datetime.now().timestamp() - ts) // 60)
    if mins < 60:
        return f"{mins}m ago"
    if mins < 60 * 24:
        return f"{mins // 60}h ago"
    return f"{mins // (60 * 24)}d ago"


def latest_drafts() -> dict[str, tuple[float, dict]]:
    """Newest draft per PR key, matched against the repos in config.toml."""
    names = {r.replace("/", "-"): r for r in CONFIG["repos"]}
    out: dict[str, tuple[float, dict]] = {}
    for path in (HOME / "drafts").glob("*.json"):
        m = DRAFT_RE.match(path.name)
        if not m:
            continue
        repo = names.get(f"{m['owner']}-{m['repo']}")
        if not repo:
            continue
        key, ts = f"{repo}#{m['num']}", float(m["ts"])
        if key not in out or ts > out[key][0]:
            try:
                out[key] = (ts, json.loads(path.read_text()))
            except json.JSONDecodeError:
                continue
    return out


def todays_log() -> list[str]:
    path = HOME / "logs" / f"{dt.date.today()}.log"
    return path.read_text().splitlines() if path.exists() else []


def last_errors(lines: list[str]) -> dict[str, tuple[float, str]]:
    errors = {}
    for line in lines:
        m = re.match(r"^(\S+) NOTIFY error: (\S+#\d+): (.*)$", line)
        if m:
            errors[m[2]] = (dt.datetime.fromisoformat(m[1]).timestamp(), m[3])
    return errors


def classify(key: str, entry: dict, draft: tuple[float, dict] | None, error: tuple[float, str] | None) -> tuple[str, str]:
    """(group, one-line description) for one PR."""
    draft_ts, d = draft or (0.0, {})
    if error and error[0] > draft_ts:
        return "error", error[1][:110]
    if entry.get("round", 0) > CONFIG["max_rounds"]:
        return "needs_you", f"stopped after {CONFIG['max_rounds']} rounds"
    if not d:
        return "seen", "no review posted by this job"
    if d.get("approve"):
        posted = d.get("mode") == "live"
        return ("approved" if posted else "ready"), "approved" if posted else f"draft only ({d.get('mode')} mode)"
    if d.get("action") == "review":
        findings = d.get("findings", [])
        if not findings:
            return "waiting_checks", "no problems found, approval held back"
        must = sum(f["severity"] == "must-fix" for f in findings)
        return "waiting_author", f"{len(findings)} comment(s) posted" + (f", {must} must fix" if must else "")
    verdicts = d.get("verdicts", [])
    human = sum(v["verdict"] == "needs_human" for v in verdicts)
    still = sum(v["verdict"] not in SETTLED for v in verdicts)
    if human:
        return "needs_you", f"{human} comment(s) need your decision"
    if still:
        return "waiting_author", f"{still} comment(s) not fixed yet"
    if d.get("review"):
        return "waiting_author", "new comments on the latest changes"
    return "waiting_checks", "every comment handled, approval held back"


def main() -> int:
    config.load()
    state = load_state()
    drafts = latest_drafts()
    lines = todays_log()
    errors = last_errors(lines)

    try:
        config.ME = github.my_login()
        open_keys: set[str] | None = set(github.candidates())
    except Exception as exc:  # offline still gives a useful report
        open_keys = None
        print(paint(f"GitHub not reachable ({exc}); showing local data only.", "33"))

    keys = sorted(set(state) | set(drafts) | (open_keys or set()))
    rows: dict[str, list[str]] = {g: [] for g in GROUPS}
    for key in keys:
        if key.split("#")[0] not in CONFIG["repos"]:
            continue
        entry = state.get(key, {})
        draft = drafts.get(key)
        if open_keys is not None and key not in open_keys:
            group, text = "closed", ""
        elif key not in state and not draft:
            group, text = "queued", "not reviewed yet"
        else:
            group, text = classify(key, entry, draft, errors.get(key))
        when = ago(draft[0]) if draft else ago(None)
        rnd = f"round {entry['round']}" if entry.get("round") else ""
        rows[group].append(f"  {key:<38} {rnd:<8} {when:<9} {text}")

    status = "paused (PAUSE file)" if PAUSE_FILE.exists() else ("running now" if LOCK_DIR.exists() else "idle")
    cycles = [l for l in lines if "cycle done" in l]
    last = cycles[-1].split(" ", 1) if cycles else None
    head = f"Auto-review  mode={CONFIG['mode']}  job={status}"
    if last:
        head += f"  last cycle {ago(dt.datetime.fromisoformat(last[0]).timestamp())} ({last[1].removeprefix('cycle done: ')})"
    print(paint(head, "1"))

    for group, (title, colour) in GROUPS.items():
        if not rows[group] or (group == "closed" and "--all" not in sys.argv):
            continue
        print()
        print(paint(f"{title} ({len(rows[group])})", f"1;{colour}"))
        print("\n".join(rows[group]))
    hidden = len(rows["closed"])
    if hidden and "--all" not in sys.argv:
        print(paint(f"\n{hidden} PR(s) no longer waiting on you are hidden; add --all to list them.", "2"))
    return 0
