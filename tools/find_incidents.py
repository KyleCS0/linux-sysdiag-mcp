"""
tools/find_incidents.py

Scans recent boots on a6k for incident clusters.

High-level flow per boot:
  1. Run journalctl with keyword grep → significant events
  2. Run journalctl tail (last 50 entries) → detect shutdown type
  3. Merge keyword events + synthetic shutdown event, sort by time
  4. Cluster by 10-minute gap → each cluster = one incident
  5. Collect all incidents from all boots, return newest-first

Why keyword grep + separate tail?
  journalctl --grep only returns matching lines — it won't show the final
  "Reached target reboot.target" line unless that line also matched the grep.
  We need the tail separately to see how the boot ended.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

# All timestamps in this tool are tagged as CST (+08:00) for consistency
# with the parsers and with what the LLM receives from get_context.
_CST_TZ = timezone(timedelta(hours=8))

from parsers.journal import parse_events

# ── Shutdown detection markers ─────────────────────────────────────────────

# journalctl logs these near the end of a clean shutdown/reboot sequence.
# If none appear in the last ~50 entries, the machine hard-locked.
# Tuple of (marker_substring, shutdown_type_string).
CLEAN_SHUTDOWN_MARKERS = [
    ("Reached target reboot.target",   "clean_reboot"),
    ("Reached target poweroff.target", "clean_shutdown"),
    ("Stopped target Default",         "clean_shutdown"),  # alternative on some kernels
    ("Journal stopped",                "clean_shutdown"),  # journald's own final entry
]

# ── Clustering gap ─────────────────────────────────────────────────────────

CLUSTER_GAP_MINUTES = 10


# ── Step 1: Parse boot list ────────────────────────────────────────────────

def parse_boot_list(raw: str) -> list[tuple[int, str]]:
    """
    Parse `journalctl --list-boots` output into (idx, boot_id) pairs.

    Format (each line):
        -5 abc123def456... Mon 2026-03-23 10:00:00 UTC—Mon 2026-03-23 12:00:00 UTC
         0 xyz789...       Sun 2026-04-05 08:00:00 UTC—Sun 2026-04-05 09:00:00 UTC

    The first token is the integer index (negative = past boots, 0 = current).
    The second token is the boot ID (hex string).
    We don't need the timestamps — journalctl -b N handles the time range.

    Returns list of (idx, boot_id), in the order journalctl provides them
    (oldest first). Caller reverses to get newest first.
    """
    boots = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            idx = int(parts[0])
            boot_id = parts[1]
            boots.append((idx, boot_id))
        except (ValueError, IndexError):
            continue
    return boots


# ── Step 2: Detect shutdown type ──────────────────────────────────────────

def detect_shutdown_type(tail_raw: str) -> str:
    """
    Determine how a boot ended by checking the last ~50 journal entries.

    Args:
        tail_raw: JSON journal output from the final 50 entries of a boot

    Returns:
        "clean_reboot"   — system was asked to reboot gracefully
        "clean_shutdown" — system was asked to power off gracefully
        "hard_lockup"    — no clean shutdown marker found; machine froze or
                           was hard-reset (kernel panic, OOM, watchdog, etc.)
    """
    # We only need the MESSAGE text, not full parse_events filtering.
    # Read raw JSON lines and extract messages directly.
    messages = []
    for line in tail_raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = entry.get("MESSAGE", "")
        if isinstance(msg, str):
            messages.append(msg)

    for msg in messages:
        for marker, shutdown_type in CLEAN_SHUTDOWN_MARKERS:
            if marker in msg:
                return shutdown_type

    return "hard_lockup"


def _last_timestamp(tail_raw: str) -> str | None:
    """
    Extract the ISO timestamp of the last parseable entry in a tail dump.
    Used as the synthetic shutdown event time.
    """
    last_ts = None
    for line in tail_raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            ts_us = int(entry["__REALTIME_TIMESTAMP"])
            dt = datetime.fromtimestamp(ts_us / 1_000_000, tz=_CST_TZ)
            last_ts = dt.isoformat()
        except (KeyError, ValueError, OSError):
            continue
    return last_ts


# ── Step 3: Cluster events ────────────────────────────────────────────────

def cluster_events(events: list[dict]) -> list[list[dict]]:
    """
    Group a sorted event list into clusters by time proximity.

    A new cluster starts whenever the gap between consecutive events exceeds
    CLUSTER_GAP_MINUTES. This groups related events (e.g., OOM kill followed
    by watchdog failures 3 minutes later) into a single incident, while
    keeping unrelated events in separate incidents.

    Args:
        events: List of event dicts with "time" as ISO 8601 string,
                sorted ascending by time.

    Returns:
        List of clusters, each cluster a list of event dicts.
        Empty input → empty output.
    """
    if not events:
        return []

    clusters = []
    current_cluster = [events[0]]

    for event in events[1:]:
        prev_time = datetime.fromisoformat(current_cluster[-1]["time"])
        curr_time = datetime.fromisoformat(event["time"])
        gap = curr_time - prev_time

        if gap > timedelta(minutes=CLUSTER_GAP_MINUTES):
            # Gap too large — start a new cluster
            clusters.append(current_cluster)
            current_cluster = [event]
        else:
            current_cluster.append(event)

    clusters.append(current_cluster)  # flush the last cluster
    return clusters


# ── Step 4: Build one incident dict from a cluster ────────────────────────

def _build_incident(cluster: list[dict], boot_idx: int) -> dict:
    """
    Convert a cluster of events into the incident dict format.

    The shutdown event (if present) is included in the event list and
    contributes to the event count. This lets the agent see the full
    picture within one object.
    """
    # Find the shutdown event if one is in this cluster
    shutdown_event = next(
        (e for e in cluster if e.get("synthetic") == "shutdown"), None
    )
    has_shutdown = shutdown_event is not None
    shutdown_type = shutdown_event["shutdown_type"] if has_shutdown else None

    # Strip internal keys before returning to the caller
    clean_events = [
        {"time": e["time"], "unit": e["unit"], "message": e["message"]}
        for e in cluster
    ]

    return {
        "boot_idx":      boot_idx,
        "start_time":    cluster[0]["time"],
        "end_time":      cluster[-1]["time"],
        "event_count":   len(cluster),
        "has_shutdown":  has_shutdown,
        "shutdown_type": shutdown_type,
        "events":        clean_events,
    }


# ── Step 5: Orchestrator ──────────────────────────────────────────────────

# journalctl grep pattern — matches any of our significant keywords.
# Server-side grep is faster than piping all JSON to us and filtering in Python,
# especially for long boots.
_GREP_PATTERN = "|".join([
    "Out of memory: Killed",
    "Watchdog timeout",
    "Failed with result 'watchdog'",
    "Failed with result 'signal'",
    "Failed with result 'oom-kill'",
    "Failed with result 'killed'",
    "Xid",
    "hung_task",
    "softlockup",
])


async def find_incidents(ssh, start_from: int = 0, num_boots: int = 5) -> list[dict]:
    """
    Scan `num_boots` boots on a6k starting at offset `start_from`.

    Args:
        ssh:        SSHClient connected to a6k
        start_from: How many boots back to start (0 = current boot).
                    start_from=0 → boots 0, -1, -2, -3, -4
                    start_from=5 → boots -5, -6, -7, -8, -9
        num_boots:  How many boots to scan (default 5)

    Returns:
        Flat list of incident dicts, sorted newest-first.
        Empty list if the requested range is beyond available history.
        Clean boots with no keyword events still appear (event_count=1,
        just the shutdown event). The agent decides what's interesting.
    """
    # ── 1. Get boot list ──────────────────────────────────────────────────
    stdout, _, _ = await ssh.sudo("journalctl --list-boots --no-pager")
    all_boots = parse_boot_list(stdout)

    # journalctl lists oldest first. Slice out the requested window.
    #
    # all_boots[-5:]        → most recent 5  (start_from=0, num_boots=5)
    # all_boots[-10:-5]     → 5 before those (start_from=5, num_boots=5)
    #
    # Python slice clamping handles out-of-range naturally:
    # if start_from exceeds history, the slice is empty → returns [].
    #
    # The `or None` on the end index is necessary because -0 == 0,
    # which would mean all_boots[-5:0] = [] instead of all_boots[-5:].
    end_idx = None if start_from == 0 else -start_from
    recent_boots = all_boots[-(start_from + num_boots):end_idx]

    # We'll collect all incidents then sort at the end
    all_incidents = []

    # ── 2. Process each boot ──────────────────────────────────────────────
    # We run all boots concurrently, but cap simultaneous SSH channels to avoid
    # hitting OpenSSH's MaxSessions limit (default: 10 per connection).
    # Each boot needs 2 channels, so a semaphore of 6 allows 3 boots in flight
    # at once (6 channels) while leaving headroom for the list-boots call above
    # and for get_context running alongside us.
    _sem = asyncio.Semaphore(6)

    async def ssh_call(cmd: str):
        async with _sem:
            return await ssh.sudo(cmd)

    async def process_boot(idx: int) -> list[dict]:
        """Return incidents for a single boot index."""

        # Parallel: keyword events + tail (for shutdown detection)
        keyword_cmd = (
            f'journalctl -b {idx} --output=json --no-pager '
            f'--grep="{_GREP_PATTERN}"'
        )
        # tail: pipe through tail -50 to get only the last 50 entries.
        # We use --output=json so we can parse timestamps.
        tail_cmd = (
            f"journalctl -b {idx} --output=json --no-pager | tail -50"
        )

        (kw_stdout, _, _), (tail_stdout, _, _) = await asyncio.gather(
            ssh_call(keyword_cmd),
            ssh_call(tail_cmd),
        )

        # Parse keyword-matched events using the shared journal parser.
        # parse_events does priority+keyword filtering, but since we already
        # grepped server-side, everything coming back is keyword-matched.
        # parse_events will still apply its own filters (e.g. binary MESSAGE).
        keyword_events = parse_events(kw_stdout)

        # Detect how this boot ended
        shutdown_type = detect_shutdown_type(tail_stdout)

        # Build synthetic shutdown event — use the last timestamp from the tail.
        # For boot 0 (current boot, still running), there's no shutdown yet.
        shutdown_event = None
        if idx != 0:
            last_ts = _last_timestamp(tail_stdout)
            if last_ts:
                shutdown_event = {
                    "time":          last_ts,
                    "unit":          "systemd",
                    "priority":      6,       # info — not an error
                    "message":       f"Boot ended: {shutdown_type}",
                    "is_error":      False,
                    "is_keyword":    False,
                    "synthetic":     "shutdown",   # internal tag
                    "shutdown_type": shutdown_type,
                }

        # Merge and sort
        all_events = list(keyword_events)
        if shutdown_event:
            all_events.append(shutdown_event)
        all_events.sort(key=lambda e: e["time"])

        # A boot with no events at all produces no incidents — skip it entirely.
        # (This shouldn't normally happen since we always add a shutdown event
        # for past boots, but guard against it.)
        if not all_events:
            return []

        # Cluster by 10-minute gap
        clusters = cluster_events(all_events)

        # Build incident dicts
        return [_build_incident(cluster, idx) for cluster in clusters]

    # Run all boots concurrently
    results = await asyncio.gather(*[process_boot(idx) for idx, _ in recent_boots])

    # Flatten and sort newest-first
    for incidents in results:
        all_incidents.extend(incidents)

    all_incidents.sort(key=lambda i: i["start_time"], reverse=True)
    return all_incidents
