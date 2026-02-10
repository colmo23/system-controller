from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, LoadingIndicator
from textual.containers import Container

from system_controller.models import ServiceConfig, Host, ServiceStatus

AUTO_REFRESH_SECONDS = 30


class MainScreen(Screen):
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("s", "stop_service", "Stop"),
        Binding("t", "restart_service", "Restart"),
        Binding("q", "quit", "Quit"),
        Binding("enter", "select_row", "View Details", show=False),
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
        connect_errors = await ssh.connect(app.hosts)

        # Fetch all statuses concurrently
        tasks = []
        for service in self.services:
            for host in self.hosts:
                tasks.append(ssh.get_service_status(host.address, service.name))

        self._statuses = await asyncio.gather(*tasks)

        self._populate_table()

    def _populate_table(self) -> None:
        table = self.query_one("#service-table", DataTable)
        table.clear()
        for status in self._statuses:
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
        """Re-fetch statuses without reconnecting."""
        import asyncio

        ssh = self.app.ssh_backend
        tasks = []
        for service in self.services:
            for host in self.hosts:
                tasks.append(ssh.get_service_status(host.address, service.name))
        self._statuses = await asyncio.gather(*tasks)
        self._populate_table()

    def action_refresh(self) -> None:
        self.query_one("#loading").display = True
        self.query_one("#table-container").display = False
        self.run_worker(self._fetch_statuses(), exclusive=True)

    def action_quit(self) -> None:
        self.app.exit()

    def action_select_row(self) -> None:
        table = self.query_one("#service-table", DataTable)
        if table.row_count == 0:
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        key_str = str(row_key)
        if "@" not in key_str:
            return
        service_name, host = key_str.split("@", 1)

        # Find the service config
        service_config = None
        for svc in self.services:
            if svc.name == service_name:
                service_config = svc
                break
        if service_config is None:
            return

        from system_controller.screens.detail import DetailScreen
        self.app.push_screen(DetailScreen(service_config, host))

    def _get_selected_service_host(self) -> tuple[str, str] | None:
        table = self.query_one("#service-table", DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        key_str = str(row_key)
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
