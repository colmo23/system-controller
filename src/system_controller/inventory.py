import re

from system_controller.models import Host


def load_inventory(path: str) -> list[Host]:
    hosts = []
    current_group = "ungrouped"

    with open(path) as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue

            group_match = re.match(r"^\[([^\]]+)\]", line)
            if group_match:
                current_group = group_match.group(1)
                continue

            # Take the first token as the host address (ignore ansible vars after it)
            address = line.split()[0]
            hosts.append(Host(address=address, group=current_group))

    return hosts
