import os
import subprocess
import tempfile

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from system_controller.models import ServiceConfig


class DetailScreen(Screen):
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("s", "stop_service", "Stop"),
        Binding("t", "restart_service", "Restart"),
    ]

    CSS = """
    #detail-title {
        dock: top;
        height: 1;
        background: $accent;
        color: $text;
        padding: 0 1;
    }
    DataTable {
        height: 1fr;
    }
    """

    def __init__(self, service: ServiceConfig, host: str):
        super().__init__()
        self.service = service
        self.host = host

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"  {self.service.name} @ {self.host}", id="detail-title")
        yield DataTable(id="detail-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#detail-table", DataTable)
        table.add_columns("Type", "Name")
        table.cursor_type = "row"

        table.add_row("Journal", self.service.name, key="journal")
        for i, fpath in enumerate(self.service.files):
            table.add_row("File", os.path.basename(fpath), key=f"file:{i}")
        for i, cmd in enumerate(self.service.commands):
            table.add_row("Command", cmd, key=f"cmd:{i}")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        self.run_worker(self._fetch_and_view(key), exclusive=True, group="view")

    async def _fetch_and_view(self, key: str) -> None:
        ssh = self.app.ssh_backend

        if key == "journal":
            content = await ssh.get_journal(self.host, self.service.name)
            suffix = ".log"
        elif key.startswith("file:"):
            i = int(key.removeprefix("file:"))
            fpath = self.service.files[i]
            content = await ssh.read_file(self.host, fpath)
            _, ext = os.path.splitext(fpath)
            suffix = ext or ".txt"
        elif key.startswith("cmd:"):
            i = int(key.removeprefix("cmd:"))
            content = await ssh.run_command(self.host, self.service.commands[i])
            suffix = ".txt"
        else:
            return

        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(content)
            with self.app.suspend():
                subprocess.run(["vim", "-R", tmp_path])
        finally:
            os.unlink(tmp_path)

    def _do_service_action(self, action: str) -> None:
        from system_controller.screens.confirm import ConfirmScreen

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                self.run_worker(
                    self._execute_service_action(action),
                    exclusive=True,
                    group="action",
                )

        self.app.push_screen(
            ConfirmScreen(action, self.service.name, self.host),
            callback=on_confirm,
        )

    async def _execute_service_action(self, action: str) -> None:
        ssh = self.app.ssh_backend
        if action == "stop":
            result = await ssh.stop_service(self.host, self.service.name)
        else:
            result = await ssh.restart_service(self.host, self.service.name)
        error = result.strip() if result.strip() else None
        if error:
            self.notify(f"{action.title()} {self.service.name}: {error}", severity="error", timeout=5)
        else:
            self.notify(f"{action.title()}ped {self.service.name} on {self.host}", timeout=3)

    def action_stop_service(self) -> None:
        self._do_service_action("stop")

    def action_restart_service(self) -> None:
        self._do_service_action("restart")

    def action_go_back(self) -> None:
        self.dismiss()
