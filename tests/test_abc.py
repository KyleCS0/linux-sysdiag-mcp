"""Test cross-machine health checks on abc."""
import asyncio
import sys
sys.path.insert(0, "..")
from core.ssh_client import manager


async def main():
    print("=== Testing abc health checks ===\n")

    # Basic health
    print("[abc] uptime + NIS/NFS service status...")
    out, err, code = await manager.abc.run(
        "uptime && systemctl is-active ypserv nfs-server"
    )
    print(f"  {out.strip()}")

    print()

    # Windowed journal errors — adjust window to match the incident under investigation
    print("[abc] journal errors in example window...")
    out, err, code = await manager.abc.sudo(
        'journalctl --no-pager --since "2026-03-24 11:40" --until "2026-03-24 12:40" -p err'
    )
    lines = [l for l in out.splitlines() if l.strip() and not l.startswith("-")]
    if lines:
        print(f"  {len(lines)} errors:")
        for l in lines:
            print(f"  {l}")
    else:
        print("  No errors in window (expected — abc was healthy)")

    await manager.close_all()
    print("\nDone.")


asyncio.run(main())
