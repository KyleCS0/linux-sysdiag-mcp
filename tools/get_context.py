"""
tools/get_context.py

Gather all available context for a time window around an incident.

Takes an end_time and duration, computes the window, fires 9 parallel SSH
calls, passes raw output to the parsers, and assembles the report.

Call this after find_incidents identifies something worth investigating.
Use the incident's end_time as the end_time here — this pulls data from
the window leading up to the crash/event.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from parsers.journal import parse_events
from parsers.sar     import parse_memory, parse_cpu, parse_swap, parse_load
from parsers.ipmi    import parse_sel
from parsers.last    import parse_sessions

# Taiwan CST = UTC+8 — used to convert UTC to local time for SSH commands
_CST_OFFSET = timedelta(hours=8)

# SSH channel cap — same reasoning as find_incidents
_SEMAPHORE_LIMIT = 6


def _parse_abc_status(raw: str, journal_events: list[dict]) -> dict:
    """
    Parse `uptime && systemctl is-active ypserv nfs-server` output.

    Output format (3 lines):
      " 21:18:58 up 213 days,  1:30,  4 users,  load average: 0.05, 0.10, 0.09"
      "active"
      "active"
    """
    lines = [l.strip() for l in raw.splitlines() if l.strip()]

    load   = "unknown"
    ypserv = "unknown"
    nfs    = "unknown"

    status_lines = []
    for line in lines:
        if "load average" in line:
            idx = line.find("load average:")
            if idx != -1:
                load = line[idx + len("load average:"):].strip()
        else:
            status_lines.append(line)

    if len(status_lines) >= 1:
        ypserv = status_lines[0]
    if len(status_lines) >= 2:
        nfs = status_lines[1]

    return {
        "ypserv": ypserv,
        "nfs":    nfs,
        "load":   load,
        "errors": [e["message"] for e in journal_events],
    }


async def get_context(ssh_manager, end_time: str, duration_minutes: int = 30) -> dict:
    """
    Gather all available context for the window [end_time - duration, end_time].

    Args:
        ssh_manager:      SSHManager with .a6k and .abc
        end_time:         ISO 8601 string — use the incident's end_time
        duration_minutes: how far back from end_time to look (default 30)

    Returns:
        {
          "window":   {"start": str, "end": str}
          "memory":   {peak_pct, peak_commit_pct, peak_time, samples} | null
          "cpu":      {peak_busy_pct, peak_iowait_pct, peak_time, samples} | null
          "swap":     {any_activity, samples} | null
          "load":     {peak_blocked, samples} | null
          "journal":  {"events": [...]}
          "ipmi":     {"events": [...]}
          "sessions": {"active": [...]}
          "abc":      {"ypserv": str, "nfs": str, "load": str, "errors": [...]}
        }

    Note: sar data may be incomplete if the window spans midnight (two sa files
    needed). For a 30-minute window this is rare; extend if needed later.
    """
    # ── Parse and compute window ──────────────────────────────────────────
    end_utc = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
    if end_utc.tzinfo is None:
        end_utc = end_utc.replace(tzinfo=timezone.utc)
    else:
        end_utc = end_utc.astimezone(timezone.utc)   # normalize +08:00 or any offset

    start_utc = end_utc - timedelta(minutes=duration_minutes)

    # Convert to local time for journalctl and sar (both use server local time)
    start_local = start_utc + _CST_OFFSET
    end_local   = end_utc   + _CST_OFFSET

    # journalctl: "YYYY-MM-DD HH:MM:SS"
    start_jctl = start_local.strftime("%Y-%m-%d %H:%M:%S")
    end_jctl   = end_local.strftime("%Y-%m-%d %H:%M:%S")

    # sar: use -e only (no -s) to avoid a sar quirk where -s with -e returns
    # nothing if no sample exists at exactly the start time. We filter samples
    # to the window in Python after parsing.
    end_sar  = end_local.strftime("%H:%M:%S")
    sar_file = f"/var/log/sysstat/sa{end_local.strftime('%d')}"

    # ── 9 parallel SSH calls ──────────────────────────────────────────────
    sem = asyncio.Semaphore(_SEMAPHORE_LIMIT)

    async def go(client, cmd, sudo=False):
        async with sem:
            return await (client.sudo(cmd) if sudo else client.run(cmd))

    (
        (jctl_a6k, _, _),
        (sar_r,    _, _),
        (sar_u,    _, _),
        (sar_w,    _, _),
        (sar_q,    _, _),
        (ipmi_raw, _, _),
        (last_raw, _, _),
        (jctl_abc, _, _),
        (abc_raw,  _, _),
    ) = await asyncio.gather(
        go(ssh_manager.a6k, f'journalctl --since "{start_jctl}" --until "{end_jctl}" --output=json --no-pager', sudo=True),
        go(ssh_manager.a6k, f'sar -r -e {end_sar} -f {sar_file}'),
        go(ssh_manager.a6k, f'sar -u -e {end_sar} -f {sar_file}'),
        go(ssh_manager.a6k, f'sar -W -e {end_sar} -f {sar_file}'),
        go(ssh_manager.a6k, f'sar -q -e {end_sar} -f {sar_file}'),
        go(ssh_manager.a6k, 'ipmitool sel list', sudo=True),
        go(ssh_manager.a6k, 'last -F'),
        go(ssh_manager.abc, f'journalctl --since "{start_jctl}" --until "{end_jctl}" --output=json --no-pager', sudo=True),
        go(ssh_manager.abc, 'uptime && systemctl is-active ypserv nfs-server'),
    )

    # ── Parse ─────────────────────────────────────────────────────────────
    journal_events = parse_events(jctl_a6k)
    abc_events     = parse_events(jctl_abc)

    mem  = parse_memory(sar_r)
    cpu  = parse_cpu(sar_u)
    swap = parse_swap(sar_w)
    load = parse_load(sar_q)

    # sar commands use -e only (no -s) to work around a sar quirk.
    # The parsers return all samples up to end time, so filter to window here.
    # Samples are now +08:00 strings; use datetime comparison (not string) to
    # correctly compare across timezone offsets.
    def _filter_samples(result: dict | None) -> dict | None:
        if result is None:
            return None
        result["samples"] = [
            s for s in result["samples"]
            if start_utc <= datetime.fromisoformat(s["time"]).astimezone(timezone.utc) <= end_utc
        ]
        return result if result["samples"] else None

    # Journal output: strip internal parser fields before returning
    def _clean(events):
        return [
            {"time": e["time"], "unit": e["unit"], "priority": e["priority"], "message": e["message"]}
            for e in events
        ]

    _cst_tz = timezone(_CST_OFFSET)
    return {
        "window": {
            "start": start_utc.astimezone(_cst_tz).isoformat(),
            "end":   end_utc.astimezone(_cst_tz).isoformat(),
        },
        "memory":   _filter_samples(mem),
        "cpu":      _filter_samples(cpu),
        "swap":     _filter_samples(swap),
        "load":     _filter_samples(load),
        "journal":  {"events": _clean(journal_events)},
        "ipmi":     {"events": parse_sel(ipmi_raw, start_utc, end_utc)},
        "sessions": sorted({s["user"] for s in parse_sessions(last_raw, start_utc, end_utc)}),
        "abc":      _parse_abc_status(abc_raw, abc_events),
    }
