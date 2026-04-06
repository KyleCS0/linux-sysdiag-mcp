# mcp-incident-tool

A diagnostic MCP server for automated Linux incident investigation. It exposes three tools to an LLM (Claude Code) over the Model Context Protocol stdio transport, enabling the model to scan boot history, pull system telemetry, and run ad-hoc commands on remote lab machines over SSH.

## Overview

The tool targets two machines:

- **a6k** — the primary server under investigation (GPU workloads, Ubuntu 24.04)
- **abc** — the NIS/NFS authentication and home directory server

When registered with Claude Code, the model can independently diagnose hard lockups, OOM kills, hung tasks, and unclean shutdowns by correlating journal logs, hardware events, memory and CPU telemetry, and user session history.

## Prerequisites

- Python 3.12 or later
- SSH key access to both lab machines
- `sudo` privileges on a6k (for `journalctl` and `ipmitool`)
- `sysstat` installed and collecting data on a6k (`sar` must be available)

## Installation

```bash
git clone <repo-url> mcp-incident-tool
cd mcp-incident-tool
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

```
A6K_HOST=<ip address>
A6K_USER=<username>
A6K_SSH_KEY=~/.ssh/id_ed25519

ABC_HOST=<ip address>
ABC_PORT=22
ABC_USER=<username>
ABC_SSH_KEY=~/.ssh/id_ed25519

SUDO_PASSWORD=<sudo password for a6k>
```

The server will refuse to start if any required variable is missing.

## Registering with Claude Code

Add the following to `~/.claude.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "incident-tool": {
      "type": "stdio",
      "command": "/path/to/mcp-incident-tool/.venv/bin/python",
      "args": ["/path/to/mcp-incident-tool/server.py"]
    }
  }
}
```

Use absolute paths. The server must be run from within the virtual environment that has the dependencies installed.

## Tools

### `find_incidents`

Scans recent boot cycles on a6k and returns clusters of error events. Start here when investigating a problem.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `start_from` | int | 0 | How many boots back to start (0 = current boot) |
| `num_boots` | int | 5 | Number of boots to scan |

Each boot produces at least one record (the shutdown event). Shutdown types: `hard_lockup`, `clean_reboot`, `clean_shutdown`. A `hard_lockup` with preceding error events is the primary signal to investigate further.

### `get_context`

Pulls all available telemetry for a time window around an incident. Use after `find_incidents` surfaces a hard lockup — pass the incident's `end_time` as the `end_time` argument.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `end_time` | str | required | ISO 8601 timestamp (e.g. `2026-03-24T14:30:00+08:00`) |
| `duration_minutes` | int | 30 | How far back from `end_time` to look |

Returns: journal errors, memory/CPU/swap/load from `sar`, IPMI hardware events, user session list, and abc NIS/NFS health in a single JSON payload.

### `run_command`

Runs an arbitrary shell command on a6k or abc as the unprivileged user. No `sudo`. Use for targeted follow-up after `get_context` surfaces a lead.

| Parameter | Type | Description |
|---|---|---|
| `machine` | str | `"a6k"` or `"abc"` |
| `command` | str | Shell command to run |

Returns `exit_code`, `stdout`, and `stderr`. A non-zero exit code is returned as data, not raised as an error.

## Project Structure

```
mcp-incident-tool/
  server.py          # MCP entry point — tool registration and transport
  core/
    config.py        # Environment variable loading (fail-fast)
    ssh_client.py    # SSHClient and SSHManager (asyncssh-based)
  tools/
    find_incidents.py  # Boot scanning and event clustering orchestrator
    get_context.py     # Parallel context aggregation orchestrator
    run_command.py     # Ad-hoc command execution
  parsers/
    journal.py       # journalctl JSON output parser
    sar.py           # sysstat/sar output parser (memory, CPU, swap, load)
    ipmi.py          # ipmitool SEL parser
    last.py          # last -F session parser
  tests/
    test_find_incidents.py  # Unit tests for clustering logic (offline)
    test_tools.py           # Integration CLI — run tools manually with args
    test_ssh.py             # SSH connectivity smoke test
    test_*.py               # Per-parser integration tests
```

## Running Tests

Unit tests (no SSH required):

```bash
source .venv/bin/activate
pytest tests/test_find_incidents.py
```

Integration tests (require SSH access and a live `.env`):

```bash
# Run any tool directly with explicit arguments
python tests/test_tools.py find_incidents --start-from 0 --num-boots 5
python tests/test_tools.py get_context --end-time "2026-03-24T14:30:00+08:00"
python tests/test_tools.py run_command a6k "uptime"
```

## Notes

- All timestamps are UTC internally. The `window` field in `get_context` output reflects the exact input times with their original offset preserved.
- IPMI timestamps use local CST (UTC+8) which is converted to UTC during parsing.
- The `sudo` password is passed via `stdin`, not on the command line, to prevent exposure in process listings.
- Do not use `print()` anywhere in `tools/` or `parsers/`. The MCP stdio transport uses stdout as the protocol pipe; any stray output corrupts the JSON-RPC framing and terminates the connection.
