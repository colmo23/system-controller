import yaml

from system_controller.models import ServiceConfig


def load_config(path: str) -> list[ServiceConfig]:
    with open(path) as f:
        data = yaml.safe_load(f)

    services = []
    for name, opts in data.get("services", {}).items():
        opts = opts or {}
        services.append(ServiceConfig(
            name=name,
            files=opts.get("files", []),
            commands=opts.get("commands", []),
        ))
    return services
