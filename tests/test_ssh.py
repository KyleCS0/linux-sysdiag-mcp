"""Test basic SSH connectivity and sudo to both machines."""
import asyncio
import sys
sys.path.insert(0, "..")
from core.ssh_client import manager


async def main():
    print("=== Testing SSH connectivity ===\n")

    # a6k basic
    print("[a6k] hostname...")
    out, err, code = await manager.a6k.run("hostname")
    print(f"  {out.strip()} (exit {code})")

    # a6k sudo
    print("[a6k] sudo whoami...")
    out, err, code = await manager.a6k.sudo("whoami")
    print(f"  {out.strip()} (exit {code})")
    if out.strip() != "root":
        print(f"  WARNING: expected root, got '{out.strip()}'. Sudo may not be working.")
        if err:
            print(f"  stderr: {err}")

    # abc basic
    print("[abc] hostname...")
    out, err, code = await manager.abc.run("hostname")
    print(f"  {out.strip()} (exit {code})")

    # abc sudo
    print("[abc] sudo whoami...")
    out, err, code = await manager.abc.sudo("whoami")
    print(f"  {out.strip()} (exit {code})")

    await manager.close_all()
    print("\nDone.")


asyncio.run(main())
