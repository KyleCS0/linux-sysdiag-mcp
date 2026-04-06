"""
parsers/sar.py

Parse `sar` output into structured performance samples.

All four parsers share the same input format:
  Line 1:  "Linux 6.17... (a6k)   03/29/2026   ..."  ← date lives here
  Line 2:  blank
  Line 3:  column headers                              ← skip
  Line 4+: data rows "HH:MM:SS AM  val1  val2 ..."
           also: "Average:" rows, "LINUX RESTART" rows ← skip both

Column indices (0-based after split on whitespace):
  All rows:  [0]=time  [1]=AM/PM  then values start at [2]

  sar -r (memory):
    [2]kbmemfree [3]kbavail [4]kbmemused [5]%memused
    [6]kbbuffers [7]kbcached [8]kbcommit  [9]%commit ...

  sar -u (CPU):
    [2]cpu [3]%user [4]%nice [5]%system [6]%iowait [7]%steal [8]%idle

  sar -W (swap):
    [2]pswpin/s  [3]pswpout/s

  sar -q (load):
    [2]runq-sz [3]plist-sz [4]ldavg-1 [5]ldavg-5 [6]ldavg-15 [7]blocked

All parsers return None if input is empty (sar file didn't exist for that date).
"""

from datetime import datetime, timedelta, timezone

# Taiwan CST = UTC+8. sar records local time; tag it as +08:00 for output.
_CST_OFFSET = timedelta(hours=8)
_CST_TZ     = timezone(_CST_OFFSET)


# ── Shared helpers ─────────────────────────────────────────────────────────

def _extract_date(lines: list[str]) -> str | None:
    """Pull the MM/DD/YYYY date string from the first Linux header line."""
    for line in lines:
        if line.startswith("Linux"):
            for part in line.split():
                if len(part) == 10 and part[2] == "/" and part[5] == "/":
                    return part
            break
    return None


def _to_iso(date_str: str | None, time_str: str) -> str:
    """
    Combine date and "HH:MM:SS AM/PM" into an ISO 8601 CST string (+08:00).
    sar records local CST (UTC+8) timestamps — tag them as +08:00.
    Falls back to the raw time string if date is unavailable.
    """
    if date_str:
        dt = datetime.strptime(f"{date_str} {time_str}", "%m/%d/%Y %I:%M:%S %p")
        return dt.replace(tzinfo=_CST_TZ).isoformat()
    return time_str


def _is_skip(line: str) -> bool:
    """True for lines that are never data rows."""
    if not line:
        return True
    if line.startswith("Linux"):
        return True
    if line.startswith("Average"):
        return True
    if "LINUX RESTART" in line:
        return True
    return False


# ── parse_memory ───────────────────────────────────────────────────────────

def parse_memory(sar_output: str) -> dict | None:
    """
    Parse `sar -r` output into memory samples.

    Returns None if output is empty (file didn't exist for that date).
    Returns:
    {
      "peak_pct":        float   # peak %memused
      "peak_commit_pct": float   # peak %commit (virtual memory overcommit)
      "peak_time":       str     # ISO 8601 UTC, time of peak %memused
      "samples": [
        {"time": str, "pct_used": float, "pct_commit": float}
      ]
    }

    %commit is important: it shows how much virtual memory processes have
    requested vs what's physically available. Crossing 100% triggers OOM.
    """
    if not sar_output or not sar_output.strip():
        return None

    lines = sar_output.splitlines()
    date_str = _extract_date(lines)
    samples = []

    for line in lines:
        line = line.strip()
        if _is_skip(line):
            continue
        if "kbmemfree" in line:
            continue  # column header

        parts = line.split()
        if len(parts) < 10:
            continue

        try:
            time_iso = _to_iso(date_str, parts[0] + " " + parts[1])
            pct_used   = float(parts[5])  # %memused
            pct_commit = float(parts[9])  # %commit
            samples.append({"time": time_iso, "pct_used": pct_used, "pct_commit": pct_commit})
        except (ValueError, IndexError):
            continue

    if not samples:
        return None

    peak = max(samples, key=lambda s: s["pct_used"])
    return {
        "peak_pct":        peak["pct_used"],
        "peak_commit_pct": peak["pct_commit"],
        "peak_time":       peak["time"],
        "samples":         samples,
    }


# ── parse_cpu ──────────────────────────────────────────────────────────────

def parse_cpu(sar_output: str) -> dict | None:
    """
    Parse `sar -u` output into CPU usage samples.

    Returns None if output is empty.
    Returns:
    {
      "peak_busy_pct":   float   # peak total CPU usage (100 - %idle)
      "peak_iowait_pct": float   # peak %iowait
      "peak_time":       str     # ISO 8601 UTC, time of peak busy
      "samples": [
        {
          "time":       str
          "pct_busy":   float   # 100 - %idle
          "pct_iowait": float   # waiting for I/O — NFS/disk stall signal
          "pct_user":   float   # userspace — compute workload signal
          "pct_system": float   # kernel — driver issue signal
        }
      ]
    }
    """
    if not sar_output or not sar_output.strip():
        return None

    lines = sar_output.splitlines()
    date_str = _extract_date(lines)
    samples = []

    for line in lines:
        line = line.strip()
        if _is_skip(line):
            continue
        if "%user" in line:
            continue  # column header

        parts = line.split()
        if len(parts) < 9:
            continue

        try:
            time_iso   = _to_iso(date_str, parts[0] + " " + parts[1])
            pct_user   = float(parts[3])
            pct_system = float(parts[5])
            pct_iowait = float(parts[6])
            pct_idle   = float(parts[8])
            pct_busy   = round(100.0 - pct_idle, 2)
            samples.append({
                "time":       time_iso,
                "pct_busy":   pct_busy,
                "pct_iowait": pct_iowait,
                "pct_user":   pct_user,
                "pct_system": pct_system,
            })
        except (ValueError, IndexError):
            continue

    if not samples:
        return None

    peak = max(samples, key=lambda s: s["pct_busy"])
    peak_iowait = max(samples, key=lambda s: s["pct_iowait"])
    return {
        "peak_busy_pct":   peak["pct_busy"],
        "peak_iowait_pct": peak_iowait["pct_iowait"],
        "peak_time":       peak["time"],
        "samples":         samples,
    }


# ── parse_swap ─────────────────────────────────────────────────────────────

def parse_swap(sar_output: str) -> dict | None:
    """
    Parse `sar -W` output into swap activity samples.

    Returns None if output is empty.
    Returns:
    {
      "any_activity": bool   # False = no swap used, can dismiss immediately
      "samples": [
        {"time": str, "pswpin": float, "pswpout": float}
      ]
    }

    pswpin/s  = pages swapped in  (reading from swap — memory pressure relief)
    pswpout/s = pages swapped out (writing to swap — kernel trying to free RAM)
    Any non-zero values mean the kernel was desperate before OOM fired.
    """
    if not sar_output or not sar_output.strip():
        return None

    lines = sar_output.splitlines()
    date_str = _extract_date(lines)
    samples = []

    for line in lines:
        line = line.strip()
        if _is_skip(line):
            continue
        if "pswpin/s" in line:
            continue  # column header

        parts = line.split()
        if len(parts) < 4:
            continue

        try:
            time_iso = _to_iso(date_str, parts[0] + " " + parts[1])
            pswpin   = float(parts[2])
            pswpout  = float(parts[3])
            samples.append({"time": time_iso, "pswpin": pswpin, "pswpout": pswpout})
        except (ValueError, IndexError):
            continue

    if not samples:
        return None

    any_activity = any(s["pswpin"] > 0 or s["pswpout"] > 0 for s in samples)
    return {
        "any_activity": any_activity,
        "samples":      samples,
    }


# ── parse_load ─────────────────────────────────────────────────────────────

def parse_load(sar_output: str) -> dict | None:
    """
    Parse `sar -q` output into load average and blocked process samples.

    Returns None if output is empty.
    Returns:
    {
      "peak_blocked": int   # max processes blocked on I/O in any sample
      "samples": [
        {"time": str, "ldavg_1": float, "blocked": int}
      ]
    }

    blocked = number of processes in uninterruptible sleep (waiting for I/O).
    High blocked count alongside high %iowait confirms I/O as the bottleneck,
    not just CPU saturation.
    """
    if not sar_output or not sar_output.strip():
        return None

    lines = sar_output.splitlines()
    date_str = _extract_date(lines)
    samples = []

    for line in lines:
        line = line.strip()
        if _is_skip(line):
            continue
        if "runq-sz" in line:
            continue  # column header

        parts = line.split()
        if len(parts) < 8:
            continue

        try:
            time_iso = _to_iso(date_str, parts[0] + " " + parts[1])
            ldavg_1  = float(parts[4])
            blocked  = int(parts[7])
            samples.append({"time": time_iso, "ldavg_1": ldavg_1, "blocked": blocked})
        except (ValueError, IndexError):
            continue

    if not samples:
        return None

    peak_blocked = max(s["blocked"] for s in samples)
    return {
        "peak_blocked": peak_blocked,
        "samples":      samples,
    }
