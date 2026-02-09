from dataclasses import dataclass, field


@dataclass
class ServiceConfig:
    name: str
    files: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)


@dataclass
class Host:
    address: str
    group: str


@dataclass
class ServiceStatus:
    service: str
    host: str
    active: bool
    status_output: str
    error: str = ""
