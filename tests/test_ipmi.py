"""Test IPMI SEL access on a6k — requires sudo."""
import asyncio
import sys
sys.path.insert(0, "..")
from core.ssh_client import manager


async def main():
    print("=== Testing IPMI SEL ===\n")

    print("[a6k] ipmitool sel list (last 10)...")
    out, err, code = await manager.a6k.sudo("ipmitool sel list")
    if code != 0:
        print(f"  FAILED (exit {code}): {err}")
    else:
        lines = [l for l in out.splitlines() if l.strip()]
        print(f"  OK — {len(lines)} total SEL entries")
        print("  Last 5:")
        for l in lines[-5:]:
            print(f"  {l}")

    await manager.close_all()
    print("\nDone.")


asyncio.run(main())
