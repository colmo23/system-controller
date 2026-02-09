from textual.app import App

from system_controller.models import ServiceConfig, Host
from system_controller.ssh import SSHBackend
from system_controller.screens.main import MainScreen


class SystemControllerApp(App):
    TITLE = "System Controller"

    CSS = """
    Screen {
        background: $surface;
    }
    """

    def __init__(self, services: list[ServiceConfig], hosts: list[Host], **kwargs):
        super().__init__(**kwargs)
        self.services = services
        self.hosts = hosts
        self.ssh_backend = SSHBackend()

    def on_mount(self) -> None:
        self.push_screen(MainScreen(self.services, self.hosts))

    async def action_quit(self) -> None:
        await self.ssh_backend.close()
        self.exit()

    async def on_unmount(self) -> None:
        await self.ssh_backend.close()
