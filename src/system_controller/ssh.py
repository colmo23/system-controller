from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import asyncssh

from system_controller.models import Host, ServiceStatus

log = logging.getLogger(__name__)


class SSHBackend:
    def __init__(self):
        self._connections: dict[str, asyncssh.SSHClientConnection] = {}

    async def connect(self, hosts: list[Host]) -> dict[str, str | None]:
        """Connect to all hosts concurrently. Returns {address: error_or_None}."""
        results: dict[str, str | None] = {}

        async def _connect_one(host: Host):
            log.info("Connecting to %s", host.address)
            try:
                ssh_config = Path.home() / ".ssh" / "config"
                config_paths = [str(ssh_config)] if ssh_config.exists() else []
                try:
                    conn = await asyncssh.connect(
                        host.address,
                        known_hosts=None,
                        config=config_paths,
                    )
                except Exception:
                    log.warning("SSH config parse failed for %s, retrying without config", host.address, exc_info=True)
                    conn = await asyncssh.connect(
                        host.address,
                        known_hosts=None,
                    )
                self._connections[host.address] = conn
                results[host.address] = None
                log.info("Connected to %s", host.address)
            except Exception as exc:
                log.error("SSH connection failed for %s: %s", host.address, exc, exc_info=True)
                results[host.address] = str(exc)

        await asyncio.gather(*[_connect_one(h) for h in hosts])
        return results

    async def get_service_status(self, host: str, service: str) -> ServiceStatus:
        conn = self._connections.get(host)
        if conn is None:
            log.warning("Status check skipped for %s on %s: not connected", service, host)
            return ServiceStatus(
                service=service, host=host, active=False,
                status_output="", error="Not connected",
            )
        try:
            result = await conn.run(f"systemctl status {service}", check=False)
            output = result.stdout or ""
            # systemctl: 0 = active, 3 = inactive, 4 = not found
            if result.exit_status == 4:
                log.info("Service %s not found on %s (exit code 4)", service, host)
                return ServiceStatus(
                    service=service, host=host, active=False,
                    status_output=output, not_found=True,
                )
            active = result.exit_status == 0
            log.debug("Service %s on %s: %s (exit code %d)", service, host, "active" if active else "inactive", result.exit_status)
            return ServiceStatus(
                service=service, host=host, active=active,
                status_output=output,
            )
        except Exception as exc:
            log.error("Failed to get status of %s on %s: %s", service, host, exc)
            return ServiceStatus(
                service=service, host=host, active=False,
                status_output="", error=str(exc),
            )

    async def stop_service(self, host: str, service: str) -> str:
        return await self.run_command(host, f"sudo systemctl stop {service}")

    async def restart_service(self, host: str, service: str) -> str:
        return await self.run_command(host, f"sudo systemctl restart {service}")

    async def get_journal(self, host: str, service: str, lines: int = 200) -> str:
        return await self.run_command(
            host, f"journalctl -u {service} --no-pager -n {lines}"
        )

    async def read_file(self, host: str, path: str) -> str:
        return await self.run_command(host, f"cat {path}")

    async def run_command(self, host: str, command: str) -> str:
        conn = self._connections.get(host)
        if conn is None:
            log.warning("Command skipped on %s (not connected): %s", host, command)
            return f"[Error: not connected to {host}]"
        log.info("Running command on %s: %s", host, command)
        try:
            result = await conn.run(command, check=False)
            output = result.stdout or ""
            stderr = result.stderr or ""
            if stderr:
                log.warning("Command stderr on %s (%s): %s", host, command, stderr.strip())
                output += f"\n--- stderr ---\n{stderr}"
            log.debug("Command on %s finished (exit %d): %s", host, result.exit_status, command)
            return output
        except Exception as exc:
            log.error("Command failed on %s (%s): %s", host, command, exc)
            return f"[Error: {exc}]"

    async def close(self):
        log.info("Closing %d SSH connection(s)", len(self._connections))
        for conn in self._connections.values():
            conn.close()
        self._connections.clear()
