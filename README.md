# mcp-incident-tool

An MCP server for Linux incident diagnosis. Gives AI coding agents structured
access to multi-server diagnostics without flooding the context window with raw logs.

## The Problem

AI agents are good at root-cause analysis, but they need the right data first.
Diagnosing a crash typically means SSHing into multiple machines, scraping
journalctl, sar, ipmitool, and last, then figuring out which boot contained the
failure. Raw journalctl output for one boot can exceed 100,000 lines — dumping
that into a chat context buries the signal and exhausts the token budget before
any real analysis happens.

This tool collects, filters, and structures that data so the agent can reason
over it efficiently.

## Tools

### `find_incidents`

Scans recent boot cycles and clusters error events by time proximity into discrete
incidents. A boot with 80,000 log lines typically produces 5 to 20 structured
events. The agent gets a timeline, not a dump.

```json
[
  {
    "boot_idx": 0,
    "start_time": "2026-03-24T11:32:00+08:00",
    "end_time":   "2026-03-24T11:58:44+08:00",
    "shutdown_type": "hard_lockup",
    "event_count": 6,
    "events": [
      { "time": "2026-03-24T11:32:00+08:00", "unit": "kernel",
        "message": "Out of memory: Killed process 8821 (java) total-vm:48329416kB" },
      { "time": "2026-03-24T11:34:12+08:00", "unit": "kernel",
        "message": "INFO: task kworker blocked for more than 120 seconds" },
      { "time": "2026-03-24T11:58:44+08:00", "unit": "systemd",
        "message": "Boot ended: hard_lockup" }
    ]
  }
]
```

The agent sees: boot 0, hard lockup, 6 events, OOM followed by a hung task.
It calls `get_context` with the `end_time` to pull the full picture.

### `get_context`

Takes a timestamp and fires 9 SSH calls in parallel across both servers,
returning a single structured payload for the window `[end_time - duration, end_time]`.
The typical usage is passing an incident's `end_time` from `find_incidents`, but
any point in time works.

| Source | What it answers |
|---|---|
| `journalctl` (primary server) | What services failed and when |
| `sar -r` memory | Was RAM exhausted? Was virtual overcommit high? |
| `sar -u` CPU | Was `%iowait` spiking? Was the kernel saturated? |
| `sar -W` swap | Was the kernel paging before OOM fired? |
| `sar -q` load | How many processes were blocked on I/O? |
| `ipmitool sel` | Any hardware events? Rules out hardware failure. |
| `last -F` sessions | Who was logged in when the machine died? |
| `journalctl` (auth server) | Was NFS or NIS a factor? |
| `uptime` + service status (auth server) | Is the NIS/NFS stack healthy? |

```json
{
  "window":  { "start": "2026-03-24T11:28:00+08:00", "end": "2026-03-24T11:58:00+08:00" },
  "memory":  { "peak_pct": 94.7, "peak_commit_pct": 98.2, "peak_time": "2026-03-24T11:40:00+08:00" },
  "cpu":     { "peak_busy_pct": 83.2, "peak_iowait_pct": 76.4 },
  "swap":    { "any_activity": false },
  "load":    { "peak_blocked": 47 },
  "ipmi":    { "events": [] },
  "abc":     { "ypserv": "active", "nfs": "active", "load": "0.12, 0.08, 0.05" }
}
```

From this: RAM hit 94%, virtual commit at 98%, iowait spiked to 76% with 47
blocked processes, hardware was clean, NFS was up. The OOM triggered a task queue
seizure that locked the machine.

### `run_command`

Runs an arbitrary shell command on either server as the unprivileged user.
No sudo. Used for targeted follow-up when the agent wants to chase a lead.

```
run_command("a6k", "getent passwd 1031")   # who owns a UID from the OOM log?
run_command("a6k", "ls -lh /var/crash/")  # any kernel crash dumps?
run_command("a6k", "nvidia-smi")           # GPU driver state
```

## Prerequisites

- Python 3.12+
- SSH key access to the target machines
- `sysstat` collecting data on the primary server
- NOPASSWD sudoers on the primary server for `journalctl` and `ipmitool`:

```bash
echo 'your_user ALL=(root) NOPASSWD: /usr/bin/journalctl, /usr/bin/ipmitool' \
  | sudo tee /etc/sudoers.d/mcp-incident
```

## Installation

```bash
git clone <repo-url> mcp-incident-tool
cd mcp-incident-tool
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

```bash
cp .env.example .env
```

```
A6K_HOST=<primary server IP>
A6K_USER=<username>
A6K_SSH_KEY=~/.ssh/id_ed25519

ABC_HOST=<auth server IP>
ABC_PORT=22
ABC_USER=<username>
ABC_SSH_KEY=~/.ssh/id_ed25519
```

The server exits immediately on startup if any required variable is missing.

## Connecting to Claude Code

Add to `~/.claude.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "incident-tool": {
      "type": "stdio",
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["/absolute/path/to/server.py"]
    }
  }
}
```

Use absolute paths. Claude Code spawns the server on startup and communicates
over stdin/stdout JSON-RPC.

## Project Structure

```
mcp-incident-tool/
  server.py            MCP entry point, tool registration
  core/
    config.py          Environment loading, fails fast on missing vars
    ssh_client.py      SSHClient and SSHManager (asyncssh, persistent connections)
  tools/
    find_incidents.py  Boot scanning, event clustering, shutdown detection
    get_context.py     Parallel context aggregation orchestrator
    run_command.py     Ad-hoc command execution
  parsers/
    journal.py         journalctl JSON parser, priority and keyword filtering
    sar.py             sysstat/sar parser for memory, CPU, swap, and load
    ipmi.py            ipmitool SEL hardware event log parser
    last.py            wtmp session record parser with crash detection
  tests/
    test_find_incidents.py   Offline unit tests (pytest, no SSH required)
    test_tools.py            Integration CLI, mirrors Claude's MCP call signature
    test_*.py                Per-source integration smoke tests
```

## Running Tests

Offline unit tests:

```bash
source .venv/bin/activate
pytest tests/test_find_incidents.py
```

Integration CLI:

```bash
python tests/test_tools.py find_incidents --start-from 0 --num-boots 5
python tests/test_tools.py get_context --end-time "2026-03-24T14:00:00+08:00"
python tests/test_tools.py run_command a6k "uptime"
```

See `tests/README.md` for the full breakdown of offline vs. live test categories.

## Typical Workflow

A full investigation from prompt to root cause takes three tool calls.

```
User: "Why did the server crash yesterday afternoon?"

1. find_incidents(start_from=0, num_boots=10)
   → boot -3, hard_lockup, 2026-03-24T11:58:44+08:00

2. get_context(end_time="2026-03-24T11:58:44+08:00", duration_minutes=30)
   → memory peaked at 94.7%, iowait at 76.4%, 47 processes blocked on I/O,
     OOM killed process 8821, hung_task followed 2 minutes later,
     hardware clean, NFS healthy

3. run_command("a6k", "getent passwd 1031")
   → resolves the UID from the OOM log to identify which user's workload
     triggered the cascade

Agent conclusion: a memory-heavy job exhausted RAM, the kernel OOM-killed it,
and the resulting I/O stall locked the machine. Hardware and NFS ruled out.
```

No manual SSH. No copy-pasting logs. The agent drives the investigation end to end.

## Design Notes

**Structured output over raw logs.** Raw journalctl output for one boot can be
100,000+ lines. The parsers extract only error-level and keyword-matched events.
The agent works with 5 to 20 structured records, not raw text.

**Parallel SSH for `get_context`.** The 9 data sources are independent. With
`asyncio.gather` and a semaphore to respect OpenSSH's `MaxSessions` limit, all
calls complete in the time of the slowest one, typically under 5 seconds.
