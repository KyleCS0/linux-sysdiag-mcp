"""
server.py

MCP server for a6k incident investigation.
Registers tools with FastMCP and owns the SSHManager lifecycle.

Transport: stdio — Claude Code spawns this as a child process and communicates
via stdin/stdout JSON-RPC. This means:
  - NEVER use print() — it corrupts the protocol. Use sys.stderr for debug.
  - The process starts, connects SSH, then blocks in mcp.run() waiting for calls.
  - When Claude Code shuts down, it closes stdin — this process exits.

Tools registered:
  find_incidents  — scan recent boots for incident clusters
  get_context     — pull all context for a time window around an incident
  run_command     — run an ad-hoc command on a6k or abc (no sudo)
"""

import json
import sys
from mcp.server.fastmcp import FastMCP
from core.ssh_client import manager
from tools.find_incidents import find_incidents as _find_incidents
from tools.get_context import get_context as _get_context
from tools.run_command import run_command as _run_command

mcp = FastMCP("incident-tool")


@mcp.tool()
async def find_incidents(start_from: int = 0, num_boots: int = 5) -> str:
    """
    Scan boots on a6k for incident clusters, with scrollable history.

    start_from: how many boots back to start (0 = current boot, default).
    num_boots:  how many boots to scan from that offset (default 5).

    Examples:
      start_from=0, num_boots=5  → boots 0, -1, -2, -3, -4  (most recent)
      start_from=5, num_boots=5  → boots -5, -6, -7, -8, -9  (scroll back)

    Returns empty list if the requested range is beyond available history.

    Each incident is a cluster of error events within 10 minutes of each other.
    Every past boot produces at least one incident (the shutdown event).

    Shutdown types:
      hard_lockup    — no clean shutdown marker; machine froze or was hard-reset
      clean_reboot   — graceful reboot
      clean_shutdown — graceful poweroff

    Returns JSON list of incidents, newest first. Each incident includes:
      boot_idx, start_time, end_time, event_count, has_shutdown,
      shutdown_type, events[{time, unit, message}]

    Start here when investigating a6k problems. Look for hard_lockup incidents
    and the events that preceded them.
    """
    incidents = await _find_incidents(manager.a6k, start_from=start_from, num_boots=num_boots)
    return json.dumps(incidents, indent=2)


@mcp.tool()
async def get_context(end_time: str, duration_minutes: int = 30) -> str:
    """
    Pull all available context for the window [end_time - duration, end_time].

    Use this after find_incidents identifies a hard_lockup or OOM incident.
    Pass the incident's end_time as end_time here.

    Gathers in parallel:
      - a6k journal (error-level events in window)
      - a6k memory, CPU, swap, load (sar)
      - a6k IPMI hardware events
      - a6k user sessions (who was logged in, who crashed with the machine)
      - abc journal errors + NIS/NFS service health

    Returns JSON with keys: window, memory, cpu, swap, load,
    journal, ipmi, sessions, abc.

    Null sar fields mean no data file exists for that date (machine was
    down or sysstat not running). Empty ipmi.events = hardware clean.
    """
    result = await _get_context(manager, end_time, duration_minutes=duration_minutes)
    return json.dumps(result, indent=2)


@mcp.tool()
async def run_command(machine: str, command: str) -> str:
    """
    Run a shell command on a6k or abc as the unprivileged user (no sudo).

    Use this for ad-hoc follow-up after find_incidents or get_context
    surfaces something worth investigating. Examples:
      getent passwd 1031           — who owns UID 1031?
      cat /proc/meminfo            — current memory state
      nvidia-smi                   — GPU status and process list
      ls -lh /var/crash/           — kernel crash dumps
      systemctl status snapd       — service status details

    Args:
      machine: "a6k" or "abc"
      command: any shell command, runs as kyle0, no sudo

    Returns JSON with machine, command, exit_code, stdout, stderr.
    Non-zero exit_code is returned as data, not an error — interpret in context.
    """
    result = await _run_command(manager, machine, command)
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
