"""Test sysstat/sar access on a6k."""
import asyncio
import sys
sys.path.insert(0, "..")
from core.ssh_client import manager


async def main():
    print("=== Testing sysstat/sar ===\n")

    # What sysstat files exist?
    print("[a6k] available sysstat files...")
    out, err, code = await manager.a6k.run("ls /var/log/sysstat/")
    if code != 0:
        print(f"  FAILED: {err}")
    else:
        files = out.split()
        print(f"  {len(files)} files: {', '.join(files)}")

    print()

    # Read a specific day (sa06 = April 6)
    print("[a6k] sar memory for April 6 (sa06)...")
    out, err, code = await manager.a6k.run("sar -r -f /var/log/sysstat/sa06")
    if code != 0:
        print(f"  FAILED (exit {code}): {err}")
    else:
        lines = [l for l in out.splitlines() if l.strip() and not l.startswith("Linux") and not l.startswith("Average")]
        print(f"  OK — {len(lines)} samples")
        for l in lines[:5]:
            print(f"  {l}")

    print()

    # Time-windowed sar
    print("[a6k] sar memory window 09:00–10:00 on April 6...")
    out, err, code = await manager.a6k.run("sar -r -s 09:00:00 -e 10:00:00 -f /var/log/sysstat/sa06")
    lines = [l for l in out.splitlines() if l.strip() and not l.startswith("Linux") and not l.startswith("Average")]
    print(f"  {len(lines)} samples in window")
    for l in lines:
        print(f"  {l}")

    await manager.close_all()
    print("\nDone.")


asyncio.run(main())
