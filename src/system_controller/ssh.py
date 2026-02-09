from __future__ import annotations

import asyncio
from pathlib import Path

import asyncssh

from system_controller.models import Host, ServiceStatus


class SSHBackend:
    def __init__(self):
        self._connections: dict[str, asyncssh.SSHClientConnection] = {}

    async def connect(self, hosts: list[Host]) -> dict[str, str | None]:
        """Connect to all hosts concurrently. Returns {address: error_or_None}."""
        results: dict[str, str | None] = {}

        async def _connect_one(host: Host):
            try:
                ssh_config = Path.home() / ".ssh" / "config"
                config_paths = [str(ssh_config)] if ssh_config.exists() else []
                conn = await asyncssh.connect(
                    host.address,
                    known_hosts=None,
                    username=None,  # uses SSH config / current user
                    config=config_paths,
                )
                self._connections[host.address] = conn
                results[host.address] = None
            except Exception as exc:
                results[host.address] = str(exc)

        await asyncio.gather(*[_connect_one(h) for h in hosts])
        return results

    async def get_service_status(self, host: str, service: str) -> ServiceStatus:
        conn = self._connections.get(host)
        if conn is None:
            return ServiceStatus(
                service=service, host=host, active=False,
                status_output="", error="Not connected",
            )
        try:
            result = await conn.run(f"systemctl status {service}", check=False)
            output = result.stdout or ""
            # systemctl returns 0 for active, non-zero otherwise
            active = result.exit_status == 0
            return ServiceStatus(
                service=service, host=host, active=active,
                status_output=output,
            )
        except Exception as exc:
            return ServiceStatus(
                service=service, host=host, active=False,
                status_output="", error=str(exc),
            )

    async def get_journal(self, host: str, service: str, lines: int = 200) -> str:
        return await self.run_command(
            host, f"journalctl -u {service} --no-pager -n {lines}"
        )

    async def read_file(self, host: str, path: str) -> str:
        return await self.run_command(host, f"cat {path}")

    async def run_command(self, host: str, command: str) -> str:
        conn = self._connections.get(host)
        if conn is None:
            return f"[Error: not connected to {host}]"
        try:
            result = await conn.run(command, check=False)
            output = result.stdout or ""
            stderr = result.stderr or ""
            if stderr:
                output += f"\n--- stderr ---\n{stderr}"
            return output
        except Exception as exc:
            return f"[Error: {exc}]"

    async def close(self):
        for conn in self._connections.values():
            conn.close()
        self._connections.clear()
