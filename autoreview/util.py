"""Logging, subprocesses and macOS notifications."""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path

from .config import HOME


def log(msg: str) -> None:
    line = f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    logs = HOME / "logs"
    logs.mkdir(exist_ok=True)
    with open(logs / f"{dt.date.today()}.log", "a") as fh:
        fh.write(line + "\n")


def run(args: list[str], *, cwd: Path | None = None, input: str | None = None, timeout: int = 300, check: bool = True) -> str:
    proc = subprocess.run(args, cwd=cwd, input=input, capture_output=True, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:4])}… exited {proc.returncode}: {proc.stderr.strip()[:500]}")
    return proc.stdout


PR_KEY_RE = re.compile(r"\b([\w.-]+/[\w.-]+)#(\d+)\b")


def notify(title: str, message: str) -> None:
    """macOS notification. With terminal-notifier installed, clicking it opens the PR named in the message,
    and a newer alert about the same PR replaces the older one instead of stacking."""
    log(f"NOTIFY {title}: {message}")
    full_title = "Auto-review: " + title
    notifier = shutil.which("terminal-notifier") or "/opt/homebrew/bin/terminal-notifier"
    if Path(notifier).exists():
        args = [notifier, "-title", full_title, "-message", message]
        if m := PR_KEY_RE.search(message):
            args += ["-open", f"https://github.com/{m[1]}/pull/{m[2]}", "-group", f"auto-review:{m[1]}#{m[2]}"]
        if subprocess.run(args, capture_output=True).returncode == 0:
            return
    script = f"display notification {json.dumps(message)} with title {json.dumps(full_title)}"
    subprocess.run(["osascript", "-e", script], capture_output=True)
