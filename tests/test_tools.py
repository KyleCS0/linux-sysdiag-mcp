import asyncio
import sys
import argparse
import pprint

sys.path.insert(0, "..")
from core.ssh_client import manager
from tools.find_incidents import find_incidents
from tools.get_context import get_context
from tools.run_command import run_command

async def _run_find_incidents(args):
    print(f"Running find_incidents with start_from={args.start_from}, num_boots={args.num_boots}...\n")
    try:
        result = await find_incidents(manager.a6k, start_from=args.start_from, num_boots=args.num_boots)
        pprint.pprint(result)
    finally:
        await manager.close_all()

async def _run_get_context(args):
    print(f"Running get_context with end_time='{args.end_time}', duration_minutes={args.duration_minutes}...\n")
    try:
        result = await get_context(manager, end_time=args.end_time, duration_minutes=args.duration_minutes)
        pprint.pprint(result)
    finally:
        await manager.close_all()

async def _run_cmd(args):
    print(f"Running run_command on '{args.machine}' with command: '{args.command}'...\n")
    try:
        result = await run_command(manager, machine=args.machine, command=args.command)
        pprint.pprint(result)
    finally:
        await manager.close_all()

def main():
    parser = argparse.ArgumentParser(description="Test MCP tools by passing arguments exactly like Claude would.")
    subparsers = parser.add_subparsers(dest="tool", required=True)

    # find_incidents subcommand
    parser_find = subparsers.add_parser("find_incidents", help="Run the find_incidents orchestrator")
    parser_find.add_argument("--start-from", type=int, default=0, help="How many boots back to start (default 0)")
    parser_find.add_argument("--num-boots", type=int, default=5, help="Number of boots to scan (default 5)")

    # get_context subcommand
    parser_ctx = subparsers.add_parser("get_context", help="Run the get_context orchestrator")
    parser_ctx.add_argument("--end-time", type=str, required=True, help="ISO 8601 end time string (e.g. '2026-04-06T14:30:00+08:00')")
    parser_ctx.add_argument("--duration-minutes", type=int, default=30, help="Duration in minutes (default 30)")

    # run_command subcommand
    parser_cmd = subparsers.add_parser("run_command", help="Run an arbitrary shell command (no sudo)")
    parser_cmd.add_argument("machine", type=str, choices=["a6k", "abc"], help="Target machine (a6k or abc)")
    parser_cmd.add_argument("command", type=str, help="Shell command to run")

    args = parser.parse_args()

    if args.tool == "find_incidents":
        asyncio.run(_run_find_incidents(args))
    elif args.tool == "get_context":
        asyncio.run(_run_get_context(args))
    elif args.tool == "run_command":
        asyncio.run(_run_cmd(args))

if __name__ == "__main__":
    main()
