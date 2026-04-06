"""
tools/run_command.py

Run an arbitrary shell command on a6k or abc as the unprivileged user.
No sudo — intentionally limited to keep the blast radius small.

Why no sudo here?
  find_incidents and get_context already cover the privileged read-only
  commands we know we need (journalctl, ipmitool). run_command is for
  ad-hoc follow-up: checking a file, running getent, reading /proc, etc.
  Giving sudo here would let Claude run anything as root, which is a
  larger risk than it's worth for a diagnostic tool.
"""

ALLOWED_MACHINES = {"a6k", "abc"}


async def run_command(ssh_manager, machine: str, command: str) -> dict:
    """
    Run a shell command on the specified machine as the unprivileged user.

    Args:
        ssh_manager: SSHManager instance (has .a6k and .abc attributes)
        machine:     "a6k" or "abc" — anything else is an error
        command:     shell string, executed as-is, no sudo

    Returns:
        {
            "machine":   str
            "command":   str
            "exit_code": int
            "stdout":    str
            "stderr":    str
        }

    Note: non-zero exit_code is a valid result, not an exception.
    The caller (Claude) decides what a non-zero exit means in context.
    """
    if machine not in ALLOWED_MACHINES:
        return {
            "machine":   machine,
            "command":   command,
            "exit_code": -1,
            "stdout":    "",
            "stderr":    f"Unknown machine '{machine}'. Must be one of: {sorted(ALLOWED_MACHINES)}",
        }

    client = getattr(ssh_manager, machine)
    stdout, stderr, exit_code = await client.run(command)

    return {
        "machine":   machine,
        "command":   command,
        "exit_code": exit_code,
        "stdout":    stdout,
        "stderr":    stderr,
    }
