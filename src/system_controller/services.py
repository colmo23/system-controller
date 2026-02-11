from __future__ import annotations

import fnmatch
import logging

from system_controller.models import ServiceConfig

log = logging.getLogger(__name__)


def _is_glob(name: str) -> bool:
    return any(c in name for c in ("*", "?", "["))


def resolve_services(
    service_configs: list[ServiceConfig],
    available_services: list[str],
) -> list[ServiceConfig]:
    """Expand glob patterns in service configs against available services.

    For each ServiceConfig whose name contains glob characters, match it
    against *available_services* and produce one ServiceConfig per match
    (inheriting files/commands from the pattern entry).

    Exact names pass through unchanged. If a concrete name is matched by
    multiple patterns, the first match wins.
    """
    resolved: list[ServiceConfig] = []
    seen: set[str] = set()

    for cfg in service_configs:
        if _is_glob(cfg.name):
            matches = [s for s in available_services if fnmatch.fnmatch(s, cfg.name)]
            log.info("Pattern %r matched %d service(s): %s", cfg.name, len(matches), matches)
            for name in matches:
                if name not in seen:
                    seen.add(name)
                    resolved.append(ServiceConfig(
                        name=name,
                        files=list(cfg.files),
                        commands=list(cfg.commands),
                    ))
        else:
            if cfg.name not in seen:
                seen.add(cfg.name)
                resolved.append(cfg)

    return resolved
