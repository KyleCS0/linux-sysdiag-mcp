# Tests

This directory contains two distinct categories of tests that must be run differently.

## Offline Unit Tests (run with pytest)

These tests have no external dependencies and run entirely in memory:

```bash
pytest test_find_incidents.py
```

`test_find_incidents.py` tests the event clustering and shutdown detection logic
using synthetic data. No SSH connection, no lab access required.

## Integration Smoke Tests (run directly with Python)

These scripts connect to the live lab machines over SSH and print raw output for
manual inspection. They are not pytest-compatible — they use `asyncio.run()` directly
and require a configured `.env` file and NOPASSWD sudoers on the target machines.

```bash
python test_ssh.py          # verify SSH connectivity and sudo
python test_journalctl.py   # verify journal access and OOM grep
python test_sar.py          # verify sysstat/sar file access
python test_ipmi.py         # verify IPMI SEL access
python test_last.py         # verify wtmp session parsing
python test_abc.py          # verify NIS/NFS health on abc
```

For end-to-end tool testing that mirrors Claude's MCP call signature exactly:

```bash
python test_tools.py find_incidents --start-from 0 --num-boots 5
python test_tools.py get_context --end-time "2026-03-24T14:30:00+08:00"
python test_tools.py run_command a6k "uptime"
```
