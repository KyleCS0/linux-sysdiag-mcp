"""
parsers/ipmi.py

Parse `ipmitool sel list` output and filter to a time window.

IPMI SEL (System Event Log) is a hardware-level event log stored in the BMC
(Baseboard Management Controller), independent of the OS. It survives reboots,
kernel panics, and power cuts. This makes it the definitive source for
hardware-caused failures.

If the SEL is clean during a crash window, hardware is eliminated as a cause.
That's negative evidence — just as useful as a positive hit.

Format (one entry per line):
  f0 | 03/24/2026 | 04:10:18 PM CST | Unknown #0xff |  | Asserted

Fields (pipe-delimited, 1-indexed after split):
  [0] entry number (hex, ignore)
  [1] date       MM/DD/YYYY
  [2] time       HH:MM:SS AM/PM TZ  — TZ is "CST" (UTC+8 on this Taiwan server)
  [3] event type — sensor name, e.g. "Physical Security #0xaa"
  [4] description — may be empty
  [5] Asserted / Deasserted

Timezone: this server uses CST = China Standard Time = UTC+8.
We subtract 8 hours to convert to UTC for comparison with the window.
"""

from datetime import datetime, timedelta, timezone


# Taiwan CST = UTC+8
_CST_OFFSET = timedelta(hours=8)
_CST_TZ     = timezone(_CST_OFFSET)


def parse_sel(raw: str, start: datetime, end: datetime) -> list[dict]:
    """
    Parse ipmitool sel list output and return events within [start, end].

    Args:
        raw:   stdout of `ipmitool sel list`
        start: window start (UTC-aware datetime)
        end:   window end   (UTC-aware datetime)

    Returns:
        List of event dicts within the window, sorted by time.
        Empty list = no hardware events = hardware clean during this window.
        [{"time": str, "type": str, "description": str}]
    """
    events = []

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split("|")
        if len(parts) < 5:
            continue

        try:
            date_str  = parts[1].strip()   # "03/24/2026"
            time_part = parts[2].strip()   # "04:10:18 PM CST"
            # Drop the timezone abbreviation — we apply UTC+8 manually
            time_str  = " ".join(time_part.split()[:2])   # "04:10:18 PM"

            dt_local = datetime.strptime(f"{date_str} {time_str}", "%m/%d/%Y %I:%M:%S %p")
            dt_cst   = dt_local.replace(tzinfo=_CST_TZ)
            dt_utc   = dt_cst.astimezone(timezone.utc)   # for window comparison
        except (ValueError, IndexError):
            continue

        # Filter to window (start/end are UTC-aware datetimes)
        if not (start <= dt_utc <= end):
            continue

        event_type  = parts[3].strip()
        description = parts[4].strip() if len(parts) > 4 else ""

        events.append({
            "time":        dt_cst.isoformat(),   # output in CST (+08:00)
            "type":        event_type,
            "description": description,
        })

    events.sort(key=lambda e: e["time"])
    return events
