"""
parsers/last.py

Parse `last -F` output into user session records.

`last` reads from /var/log/wtmp which records every login and logout.
The -F flag gives full timestamps (day month date time year) instead of
the default abbreviated format that omits the year.

Why this is useful for crash investigation:
  "- crash" entries mean the session ended because the machine crashed —
  the kernel wrote a crash marker to wtmp at shutdown time. This tells you
  who was actively logged in when the machine died, and whether their
  session spans across the incident window.

Format (one session per line):
  user0   pts/0  192.0.2.10  Mon Apr  6 16:41:49 2026   still logged in
  user1   pts/6  192.0.2.11  Mon Mar 30 18:30:31 2026 - crash           (1+21:58)
  user0   pts/0  192.0.2.10  Mon Apr  6 16:17:03 2026 - Mon Apr  6 16:17:23 2026  (00:00)
  reboot  system boot  6.17...  Sun Apr  5 16:32:45 2026   still running    <- skip

Columns (after split on whitespace):
  [0] user      [1] tty      [2] from (IP or display)
  [3..7] login time: "Mon Apr  6 16:41:49 2026"
  [8] separator token: "still" | "-"
  if "still": status = active
  if "-":
    [9] = "crash" → status = gone
    [9..13] = logout time tokens → status = ended

Timezone: server local time is CST = UTC+8. Timestamps are returned as +08:00.
"""

from datetime import datetime, timedelta, timezone


_CST_OFFSET = timedelta(hours=8)
_CST_TZ     = timezone(_CST_OFFSET)

# Entries to skip — not user sessions
_SKIP_USERS = {"reboot", "runlevel", "wtmp", "shutdown"}


def _parse_local_time(parts: list[str], start_idx: int) -> datetime | None:
    """
    Parse 5-token local time "Mon Apr  6 16:41:49 2026" into UTC datetime.
    Returns None if parsing fails.
    """
    try:
        time_str = " ".join(parts[start_idx:start_idx + 5])
        dt = datetime.strptime(time_str, "%a %b %d %H:%M:%S %Y")
        return dt.replace(tzinfo=_CST_TZ)
    except (ValueError, IndexError):
        return None


def parse_sessions(raw: str, start: datetime, end: datetime) -> list[dict]:
    """
    Parse last -F output and return sessions that overlapped [start, end].

    A session overlaps if:
      login < end  AND  (logout > start  OR  status in ["active", "gone"])

    "gone" means the session ended with the machine crash — the most
    informative status for crash investigation.

    Args:
        raw:   stdout of `last -F`
        start: window start (UTC-aware datetime)
        end:   window end   (UTC-aware datetime)

    Returns:
        [{"user": str, "from": str, "login": str, "logout": str|None, "status": str}]
        Sorted by login time ascending.
    """
    sessions = []

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) < 9:
            continue

        user = parts[0]
        if user in _SKIP_USERS or user.startswith("wtmp"):
            continue

        from_addr = parts[2]

        login_dt = _parse_local_time(parts, 3)
        if login_dt is None:
            continue

        # parts[8] is either "still" or "-"
        separator = parts[8]

        if separator == "still":
            # "still logged in" or "still running"
            status    = "active"
            logout_dt = None

        elif separator == "-":
            if len(parts) > 9 and parts[9] == "crash":
                # Session ended when machine crashed
                status    = "gone"
                logout_dt = None
            elif len(parts) >= 14:
                # Normal logout: "- Mon Apr  6 16:17:23 2026  (duration)"
                logout_dt = _parse_local_time(parts, 9)
                if logout_dt is None:
                    continue
                status = "ended"
            else:
                continue
        else:
            continue

        # Overlap filter — compare as UTC (start/end are UTC-aware)
        login_utc  = login_dt.astimezone(timezone.utc)
        logout_utc = logout_dt.astimezone(timezone.utc) if logout_dt else None
        if login_utc >= end:
            continue
        if status == "ended" and logout_utc is not None and logout_utc <= start:
            continue

        sessions.append({
            "user":   user,
            "from":   from_addr,
            "login":  login_dt.isoformat(),
            "logout": logout_dt.isoformat() if logout_dt else None,
            "status": status,
        })

    sessions.sort(key=lambda s: s["login"])
    return sessions
