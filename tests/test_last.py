"""Test last/wtmp login history on a6k."""
import asyncio
import sys
sys.path.insert(0, "..")
from core.ssh_client import manager


async def main():
    print("=== Testing last (login history) ===\n")

    # Full history with timestamps
    print("[a6k] last -F (recent 20 entries)...")
    out, err, code = await manager.a6k.run("last -F -n 20")
    if code != 0:
        print(f"  FAILED (exit {code}): {err}")
    else:
        lines = [l for l in out.splitlines() if l.strip() and not l.startswith("wtmp")]
        print(f"  OK — showing {len(lines)} entries")
        for l in lines[:10]:
            print(f"  {l}")

    print()

    # Time-bounded query — adjust window to match the incident under investigation
    print("[a6k] sessions active in example window...")
    out, err, code = await manager.a6k.run(
        'last -F -s "2026-03-24 11:00" -t "2026-03-24 14:30"'
    )
    lines = [l for l in out.splitlines() if l.strip() and not l.startswith("wtmp") and not l.startswith("begins")]
    print(f"  {len(lines)} session records")
    for l in lines:
        print(f"  {l}")

    await manager.close_all()
    print("\nDone.")


asyncio.run(main())
