"""Test journalctl access on a6k — sudo required for full system journal."""
import asyncio
import sys
sys.path.insert(0, "..")
from core.ssh_client import manager


async def main():
    print("=== Testing journalctl ===\n")

    # List boots
    print("[a6k] journalctl --list-boots...")
    out, err, code = await manager.a6k.sudo("journalctl --list-boots --no-pager")
    if code != 0:
        print(f"  FAILED (exit {code}): {err}")
    else:
        lines = [l for l in out.splitlines() if l.strip() and not l.startswith("-")]
        print(f"  OK — {len(lines)} boots found")
        for line in lines[-3:]:
            print(f"  {line}")

    print()

    # Scan for OOM kills across all boots
    print("[a6k] scanning for OOM kills (all boots)...")
    out, err, code = await manager.a6k.sudo(
        'journalctl --no-pager -k --grep="Out of memory: Killed"'
    )
    kills = [l for l in out.splitlines() if "Killed process" in l]
    print(f"  Found {len(kills)} OOM kills")
    for k in kills[-3:]:
        print(f"  {k.strip()}")

    print()

    # Time-windowed query
    print("[a6k] time-windowed query (Mar 24 11:40–12:40)...")
    out, err, code = await manager.a6k.sudo(
        'journalctl --no-pager --since "2026-03-24 11:40" --until "2026-03-24 12:40" -p err'
    )
    lines = [l for l in out.splitlines() if l.strip() and not l.startswith("-")]
    print(f"  {len(lines)} error-level entries in window")
    for l in lines[:5]:
        print(f"  {l.strip()}")

    await manager.close_all()
    print("\nDone.")


asyncio.run(main())
