from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import asyncssh

from system_controller.models import Host, ServiceStatus

log = logging.getLogger(__name__)


MAX_CONCURRENT_SESSIONS = 8


class SSHBackend:
    def __init__(self):
        self._connections: dict[str, asyncssh.SSHClientConnection] = {}
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    async def connect(self, hosts: list[Host]) -> dict[str, str | None]:
        """Connect to all hosts concurrently. Returns {address: error_or_None}."""
        results: dict[str, str | None] = {}

        async def _connect_one(host: Host):
            log.info("Connecting to %s", host.address)
            try:
                ssh_config = Path.home() / ".ssh" / "config"
                config_paths = [str(ssh_config)] if ssh_config.exists() else []
                try:
                    conn = await asyncio.wait_for(
                        asyncssh.connect(
                            host.address,
                            known_hosts=None,
                            config=config_paths,
                        ),
                        timeout=3,
                    )
                except asyncio.TimeoutError:
                    raise
                except Exception:
                    log.warning("SSH config parse failed for %s, retrying without config", host.address, exc_info=True)
                    conn = await asyncio.wait_for(
                        asyncssh.connect(
                            host.address,
                            known_hosts=None,
                        ),
                        timeout=3,
                    )
                self._connections[host.address] = conn
                results[host.address] = None
                log.info("Connected to %s", host.address)
            except asyncio.TimeoutError:
                log.error("SSH connection timed out for %s", host.address)
                results[host.address] = "Connection timed out"
            except Exception as exc:
                log.error("SSH connection failed for %s: %s", host.address, exc, exc_info=True)
                results[host.address] = str(exc)

        need_connect = [h for h in hosts if h.address not in self._connections]
        await asyncio.gather(*[_connect_one(h) for h in need_connect])
        # Carry forward existing connections as successful
        for h in hosts:
            if h.address not in results:
                results[h.address] = None
        return results

    def _semaphore(self, host: str) -> asyncio.Semaphore:
        if host not in self._semaphores:
            self._semaphores[host] = asyncio.Semaphore(MAX_CONCURRENT_SESSIONS)
        return self._semaphores[host]

    async def get_service_status(self, host: str, service: str) -> ServiceStatus:
        conn = self._connections.get(host)
        if conn is None:
            log.warning("Status check skipped for %s on %s: not connected", service, host)
            return ServiceStatus(
                service=service, host=host, active=False,
                status_output="", error="Not connected",
            )
        try:
            async with self._semaphore(host):
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
            async with self._semaphore(host):
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

    async def list_services(self, host: str) -> list[str]:
        """List all systemd service unit names on a host (without .service suffix)."""
        output = await self.run_command(
            host,
            "systemctl list-units --type=service --all --no-legend --no-pager",
        )
        services = []
        for line in output.splitlines():
            parts = line.split()
            if not parts:
                continue
            unit = parts[0]
            if unit.endswith(".service"):
                unit = unit[: -len(".service")]
            services.append(unit)
        log.info("Discovered %d services on %s", len(services), host)
        return services

    async def close(self):
        log.info("Closing %d SSH connection(s)", len(self._connections))
        for conn in self._connections.values():
            conn.close()
        self._connections.clear()
