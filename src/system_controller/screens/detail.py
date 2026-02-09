import asyncio
import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Header,
    LoadingIndicator,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from system_controller.models import ServiceConfig


class DetailScreen(Screen):
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
    ]

    CSS = """
    #detail-title {
        dock: top;
        height: 1;
        background: $accent;
        color: $text;
        padding: 0 1;
    }
    TextArea {
        height: 1fr;
    }
    TabPane {
        height: 1fr;
        padding: 0;
    }
    LoadingIndicator {
        height: 3;
    }
    """

    def __init__(self, service: ServiceConfig, host: str):
        super().__init__()
        self.service = service
        self.host = host

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"  {self.service.name} @ {self.host}", id="detail-title")
        with TabbedContent():
            with TabPane("Journal", id="tab-journal"):
                yield LoadingIndicator(id="loading-journal")
                yield TextArea(id="journal-content", read_only=True)
            for i, fpath in enumerate(self.service.files):
                tab_label = os.path.basename(fpath)
                with TabPane(tab_label, id=f"tab-file-{i}"):
                    yield LoadingIndicator(id=f"loading-file-{i}")
                    yield TextArea(id=f"file-content-{i}", read_only=True)
            for i, cmd in enumerate(self.service.commands):
                # Use first word of command as tab label
                tab_label = cmd.split()[0] if cmd else f"cmd-{i}"
                with TabPane(tab_label, id=f"tab-cmd-{i}"):
                    yield LoadingIndicator(id=f"loading-cmd-{i}")
                    yield TextArea(id=f"cmd-content-{i}", read_only=True)
        yield Footer()

    def on_mount(self) -> None:
        # Hide all content areas initially
        self.query_one("#journal-content").display = False
        for i in range(len(self.service.files)):
            self.query_one(f"#file-content-{i}").display = False
        for i in range(len(self.service.commands)):
            self.query_one(f"#cmd-content-{i}").display = False

        self.run_worker(self._fetch_all())

    async def _fetch_all(self) -> None:
        ssh = self.app.ssh_backend

        async def fetch_journal():
            journal = await ssh.get_journal(self.host, self.service.name)
            journal_area = self.query_one("#journal-content", TextArea)
            journal_area.load_text(journal)
            self.query_one("#loading-journal").display = False
            journal_area.display = True

        async def fetch_file(i: int, fpath: str):
            content = await ssh.read_file(self.host, fpath)
            area = self.query_one(f"#file-content-{i}", TextArea)
            area.load_text(content)
            self.query_one(f"#loading-file-{i}").display = False
            area.display = True

        async def fetch_command(i: int, cmd: str):
            output = await ssh.run_command(self.host, cmd)
            area = self.query_one(f"#cmd-content-{i}", TextArea)
            area.load_text(output)
            self.query_one(f"#loading-cmd-{i}").display = False
            area.display = True

        tasks = [fetch_journal()]
        for i, fpath in enumerate(self.service.files):
            tasks.append(fetch_file(i, fpath))
        for i, cmd in enumerate(self.service.commands):
            tasks.append(fetch_command(i, cmd))

        await asyncio.gather(*tasks)

    def action_go_back(self) -> None:
        self.app.pop_screen()
