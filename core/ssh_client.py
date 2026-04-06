import asyncssh
import asyncio
from core.config import A6K, ABC


class SSHClient:
    """Persistent SSH connection to a single machine."""

    def __init__(self, conn_params: dict):
        self._params = conn_params
        self._conn = None

    async def connect(self):
        if self._conn is None:
            self._conn = await asyncssh.connect(
                self._params["host"],
                port=self._params["port"],
                username=self._params["username"],
                client_keys=self._params["client_keys"],
                known_hosts=None,  # disable host key checking for lab machines
            )

    async def run(self, command: str) -> tuple[str, str, int]:
        """Run a command. Returns (stdout, stderr, exit_code)."""
        await self.connect()
        result = await self._conn.run(command, check=False)
        return result.stdout, result.stderr, result.returncode

    async def sudo(self, command: str) -> tuple[str, str, int]:
        """Run a command with sudo (non-interactive). Requires NOPASSWD sudoers on the target."""
        await self.connect()
        result = await self._conn.run(
            f"sudo -n {command}",
            check=False,
        )
        return result.stdout, result.stderr, result.returncode

    async def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


class SSHManager:
    """Manages persistent connections to all lab machines."""

    def __init__(self):
        self.a6k = SSHClient(A6K)
        self.abc = SSHClient(ABC)

    async def close_all(self):
        await self.a6k.close()
        await self.abc.close()


# Singleton for use across tools
manager = SSHManager()
