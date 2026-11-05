"""Keep the runtime folders from growing forever: old drafts and logs, stale ctx/, and launchd.log."""

from __future__ import annotations

import shutil
import time

from .config import CONFIG, HOME
from .util import log

LAUNCHD_LOG_MAX = 5 * 1024 * 1024   # trim launchd.log once it passes this…
LAUNCHD_LOG_KEEP = 1024 * 1024      # …down to its last this-many bytes


def ctx_name(key: str) -> str:
    """The ctx/ folder name for a PR key; must match workspace.write_ctx."""
    return key.replace("/", "-").replace("#", "-")


def prune(active_keys: list[str] | None) -> None:
    """Delete drafts/ and logs/*.log older than `retention_days`, and ctx/ folders of PRs not in
    `active_keys` (None skips that, e.g. for a single --pr run). ctx/ is rewritten before every
    pass, so dropping a folder never loses anything a later pass needs."""
    cutoff = time.time() - CONFIG.get("retention_days", 30) * 86400
    removed = 0

    for pattern in ("drafts/*.json", "logs/*.log"):
        for path in HOME.glob(pattern):
            if path.name != "launchd.log" and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1

    if active_keys is not None:
        keep = {ctx_name(k) for k in active_keys}
        for path in (HOME / "ctx").glob("*"):
            if path.is_dir() and path.name not in keep:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1

    launchd_log = HOME / "logs" / "launchd.log"
    if launchd_log.exists() and launchd_log.stat().st_size > LAUNCHD_LOG_MAX:
        with open(launchd_log, "r+b") as fh:
            fh.seek(-LAUNCHD_LOG_KEEP, 2)
            tail = fh.read()
            nl = tail.find(b"\n")
            if 0 <= nl < len(tail) - 1:
                tail = tail[nl + 1:]  # start on a whole line
            fh.seek(0)
            fh.write(tail)
            fh.truncate()
        log("cleanup: trimmed launchd.log")

    if removed:
        log(f"cleanup: removed {removed} old draft/log file(s) and stale ctx folder(s)")
