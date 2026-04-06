"""
parsers/journal.py

Parses `journalctl --output=json --no-pager` output into structured events.

journalctl JSON format: one JSON object per line (not a JSON array).
Each object is one log entry with many fields — we extract only what we need.

Key fields we use:
  __REALTIME_TIMESTAMP  microseconds since Unix epoch (string) — the wall-clock time
  MESSAGE               the actual log text
  PRIORITY              severity 0–7 (0=emerg, 3=err, 6=info, 7=debug)
  _SYSTEMD_UNIT         service that generated the entry, e.g. "snapd.service"
  SYSLOG_IDENTIFIER     fallback identifier, e.g. "kernel", "sshd"
"""

import json
from datetime import datetime, timedelta, timezone

# Taiwan CST = UTC+8
_CST_TZ = timezone(timedelta(hours=8))


# Significant event detection:
# We keep an entry if it matches EITHER condition:
#   1. priority <= ERROR_PRIORITY (error/critical/alert/emergency)
#   2. message contains one of these keywords — regardless of priority
#
# Why keywords in addition to priority?
# Critical events like OOM kills are logged by the kernel at priority 5 (notice),
# not at error level. Priority filtering alone would silently miss them.
# Identifiers to always skip — these produce false positives.
# "sudo" audit entries log the full command string, which contains our grep
# keywords (e.g. "Out of memory: Killed") as part of the command text.
SKIP_IDENTIFIERS = {"sudo"}

KEYWORDS = [
    "Out of memory: Killed",          # OOM kill (kernel, priority 5)
    "Watchdog timeout",               # service stopped responding to watchdog
    "Failed with result 'watchdog'",  # service killed by watchdog timeout
    "Failed with result 'signal'",    # service killed by a signal (often OOM cascade)
    "Failed with result 'oom-kill'",  # service explicitly OOM killed
    "Failed with result 'killed'",    # service killed externally
    "Xid",                            # NVIDIA GPU driver fault code
    "blocked for more than",           # hung_task primary line: "task foo:1234 blocked for more than 120 seconds"
    "hung_task",                      # hung_task secondary line containing hung_task_timeout_secs
    "softlockup",                     # CPU stuck in kernel code, not yielding
]

# Keep entries at this priority level and below.
# 3 = err. So we keep: err(3), crit(2), alert(1), emerg(0).
ERROR_PRIORITY = 3


def parse_events(raw: str) -> list[dict]:
    """
    Parse journalctl JSON output into a filtered, sorted list of significant events.

    Args:
        raw: Full stdout from `journalctl --output=json --no-pager`

    Returns:
        List of significant event dicts, sorted ascending by time.
        Empty list if no significant events found.
    """
    events = []

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        # Each line is a self-contained JSON object
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            # journalctl occasionally emits non-JSON separator lines — skip them
            continue

        # Skip known false-positive sources before doing anything else
        identifier = entry.get("SYSLOG_IDENTIFIER", "")
        if identifier in SKIP_IDENTIFIERS:
            continue

        message = entry.get("MESSAGE", "")

        # MESSAGE is sometimes a list of ints representing binary data (e.g. from
        # programs that write raw bytes to the journal). We can't grep these — skip.
        if not isinstance(message, str):
            continue

        # Parse priority — default to 7 (debug) if missing, meaning not significant
        try:
            priority = int(entry.get("PRIORITY", 7))
        except (ValueError, TypeError):
            priority = 7

        is_error_level = priority <= ERROR_PRIORITY
        is_keyword_match = any(kw in message for kw in KEYWORDS)

        # Drop entries that are neither error-level nor keyword-matched
        if not (is_error_level or is_keyword_match):
            continue

        # --- Timestamp ---
        # __REALTIME_TIMESTAMP is microseconds since Unix epoch, stored as a string.
        # Divide by 1_000_000 to get seconds, then convert to UTC datetime.
        try:
            ts_microseconds = int(entry["__REALTIME_TIMESTAMP"])
            ts = datetime.fromtimestamp(ts_microseconds / 1_000_000, tz=_CST_TZ)
        except (KeyError, ValueError, OSError):
            # If timestamp is malformed or missing, skip this entry —
            # we can't cluster or sort without a valid time.
            continue

        # --- Unit identification ---
        # _SYSTEMD_UNIT is set for systemd-managed services: "snapd.service"
        # SYSLOG_IDENTIFIER is set for everything: "kernel", "sshd", "python"
        # Prefer the more specific unit name.
        unit = entry.get("_SYSTEMD_UNIT") or entry.get("SYSLOG_IDENTIFIER", "unknown")

        events.append({
            "time":        ts.isoformat(),
            "unit":        unit,
            "priority":    priority,
            "message":     message,
            # Keep these flags so callers can distinguish why an event was kept
            "is_error":    is_error_level,
            "is_keyword":  is_keyword_match,
        })

    # Sort ascending by time — journalctl is usually ordered but not guaranteed,
    # especially when merging output from multiple queries.
    events.sort(key=lambda e: e["time"])
    return events
