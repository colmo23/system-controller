from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, LoadingIndicator
from textual.containers import Container

from system_controller.models import ServiceConfig, Host, ServiceStatus
from system_controller.services import resolve_services

AUTO_REFRESH_SECONDS = 30


class MainScreen(Screen):
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("s", "stop_service", "Stop"),
        Binding("t", "restart_service", "Restart"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    #loading {
        align: center middle;
    }
    #table-container {
        height: 1fr;
    }
    DataTable {
        height: 1fr;
    }
    """

    def __init__(self, services: list[ServiceConfig], hosts: list[Host]):
        super().__init__()
        self.services = services
        self.hosts = hosts
        self._statuses: list[ServiceStatus] = []
        self._connect_errors: dict[str, str | None] = {}
        self._resolved_services: dict[str, list[ServiceConfig]] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(LoadingIndicator(), id="loading")
        yield Container(DataTable(id="service-table"), id="table-container")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#service-table", DataTable)
        table.add_columns("Service", "Host", "Status")
        table.cursor_type = "row"
        self.query_one("#table-container").display = False
        self.run_worker(self._fetch_statuses(), exclusive=True)
        self._auto_refresh_timer = self.set_interval(
            AUTO_REFRESH_SECONDS, self._auto_refresh, pause=False,
        )

    async def _fetch_statuses(self) -> None:
        import asyncio

        app = self.app
        ssh = app.ssh_backend

        # Connect to hosts
        self._connect_errors = await ssh.connect(app.hosts)

        # Only fetch statuses for connected hosts
        connected_hosts = [h for h in self.hosts if not self._connect_errors.get(h.address)]

        # Resolve glob patterns per host
        for host in connected_hosts:
            available = await ssh.list_services(host.address)
            self._resolved_services[host.address] = resolve_services(self.services, available)

        tasks = []
        for host in connected_hosts:
            for svc in self._resolved_services[host.address]:
                tasks.append(ssh.get_service_status(host.address, svc.name))

        self._statuses = await asyncio.gather(*tasks) if tasks else []

        self._populate_table()

    def _populate_table(self) -> None:
        table = self.query_one("#service-table", DataTable)
        table.clear()

        # 1) Unreachable hosts — single row each
        for host in self.hosts:
            err = self._connect_errors.get(host.address)
            if err:
                table.add_row("-", host.address, Text("⚠ unreachable", style="bold red"), key=f"unreachable:{host.address}")

        # 2) Reachable hosts — group statuses by host
        for host in self.hosts:
            if self._connect_errors.get(host.address):
                continue
            host_statuses = [s for s in self._statuses if s.host == host.address]
            found = [s for s in host_statuses if not s.not_found]
            if not found:
                # All services are not_found on this host
                table.add_row("-", host.address, Text("no services", style="dim"), key=f"noservices:{host.address}")
            else:
                for status in found:
                    if status.error:
                        display_status = Text(f"⚠ {status.error}", style="bold red")
                    elif status.active:
                        display_status = Text("● active", style="bold green")
                    else:
                        display_status = Text("○ inactive", style="bold yellow")
                    table.add_row(status.service, status.host, display_status, key=f"{status.service}@{status.host}")

        self.query_one("#loading").display = False
        self.query_one("#table-container").display = True

    def _auto_refresh(self) -> None:
        """Called periodically to refresh statuses without showing loading overlay."""
        self.run_worker(self._refresh_statuses(), exclusive=True)

    async def _refresh_statuses(self) -> None:
        """Re-fetch statuses and retry previously-failed hosts."""
        import asyncio

        ssh = self.app.ssh_backend

        # Retry connecting to previously-failed hosts
        failed_hosts = [h for h in self.hosts if self._connect_errors.get(h.address)]
        if failed_hosts:
            retry_results = await ssh.connect(failed_hosts)
            self._connect_errors.update(retry_results)

        connected_hosts = [h for h in self.hosts if not self._connect_errors.get(h.address)]

        # Re-resolve for hosts that were just reconnected
        for host in failed_hosts:
            if not self._connect_errors.get(host.address):
                available = await ssh.list_services(host.address)
                self._resolved_services[host.address] = resolve_services(self.services, available)

        tasks = []
        for host in connected_hosts:
            for svc in self._resolved_services.get(host.address, []):
                tasks.append(ssh.get_service_status(host.address, svc.name))
        self._statuses = await asyncio.gather(*tasks) if tasks else []
        self._populate_table()

    def action_refresh(self) -> None:
        self.run_worker(self._refresh_statuses(), exclusive=True)

    def action_quit(self) -> None:
        self.app.exit()

    def _get_service_config(self, service_name: str, host: str) -> ServiceConfig | None:
        """Look up the resolved ServiceConfig for a concrete service on a host."""
        for svc in self._resolved_services.get(host, []):
            if svc.name == service_name:
                return svc
        return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key_str = event.row_key.value
        if "@" not in key_str:
            return
        service_name, host = key_str.split("@", 1)

        service_config = self._get_service_config(service_name, host)
        if service_config is None:
            return

        self._auto_refresh_timer.pause()

        def on_detail_return(_=None) -> None:
            self._auto_refresh_timer.resume()
            self.run_worker(self._refresh_statuses(), exclusive=True)

        from system_controller.screens.detail import DetailScreen
        self.app.push_screen(DetailScreen(service_config, host), callback=on_detail_return)

    def _get_selected_service_host(self) -> tuple[str, str] | None:
        table = self.query_one("#service-table", DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        key_str = row_key.value
        if "@" not in key_str:
            return None
        service_name, host = key_str.split("@", 1)
        return service_name, host

    def _do_service_action(self, action: str) -> None:
        selected = self._get_selected_service_host()
        if selected is None:
            return
        service_name, host = selected

        from system_controller.screens.confirm import ConfirmScreen

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                self.run_worker(
                    self._execute_service_action(action, service_name, host),
                    exclusive=True,
                )

        self.app.push_screen(ConfirmScreen(action, service_name, host), callback=on_confirm)

    async def _execute_service_action(self, action: str, service: str, host: str) -> None:
        ssh = self.app.ssh_backend
        if action == "stop":
            result = await ssh.stop_service(host, service)
        else:
            result = await ssh.restart_service(host, service)
        error = result.strip() if result.strip() else None
        if error:
            self.notify(f"{action.title()} {service}: {error}", severity="error", timeout=5)
        else:
            self.notify(f"{action.title()}ped {service} on {host}", timeout=3)
        await self._refresh_statuses()

    def action_stop_service(self) -> None:
        self._do_service_action("stop")

    def action_restart_service(self) -> None:
        self._do_service_action("restart")
