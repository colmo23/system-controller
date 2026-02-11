# System Controller - Technical Specification

**Version:** 0.1.0
**Last Updated:** 2026-02-10

## 1. Overview

System Controller is a terminal user interface (TUI) application for monitoring systemd services across multiple remote hosts. It connects to machines via SSH, retrieves service statuses, and presents them in an interactive dashboard. Users can drill into individual services to view journal logs, configuration files, and command outputs.

## 2. Requirements

### 2.1 Functional Requirements

- **FR-1**: Accept an Ansible-style INI inventory file defining target hosts and host groups.
- **FR-2**: Accept a YAML configuration file defining services to monitor, along with associated files and commands per service. Service names may use glob patterns (`*`, `?`, `[`) to match multiple systemd units on each host.
- **FR-3**: Establish SSH connections to all inventory hosts concurrently on startup.
- **FR-4**: Retrieve `systemctl status` for every configured service on every host.
- **FR-5**: Display a tabular overview of all service/host pairs with color-coded status indicators (active, inactive, error).
- **FR-6**: Auto-refresh service statuses every 30 seconds.
- **FR-7**: Allow manual refresh via keyboard shortcut.
- **FR-8**: Provide a detail view for any service/host pair showing:
  - `journalctl` output (last 200 lines)
  - Contents of configured files (read via `cat`)
  - Output of configured commands
- **FR-9**: Support keyboard-driven navigation between views.

### 2.2 Non-Functional Requirements

- **NFR-1**: Python >= 3.10.
- **NFR-2**: Async I/O for all SSH operations to avoid blocking the UI.
- **NFR-3**: Concurrent connection establishment and status fetching.
- **NFR-4**: Graceful handling of unreachable hosts (display error, don't crash).

## 3. Architecture

```
┌─────────────────────────────────────────────────┐
│                   CLI Layer                     │
│                  (cli.py)                       │
│         argparse → load config/inventory        │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│                 Application                     │
│                  (app.py)                       │
│         SystemControllerApp(textual.App)        │
│         Owns: services, hosts, ssh_backend      │
└────────┬───────────────────────────┬────────────┘
         │                           │
┌────────▼──────────┐    ┌──────────▼─────────────┐
│    UI Layer       │    │    Backend Layer       │
│   screens/        │    │                        │
│  ┌────────────┐   │    │  ssh.py (SSHBackend)   │
│  │ MainScreen │   │    │  config.py             │
│  └─────┬──────┘   │    │  inventory.py          │
│  ┌─────▼──────┐   │    │  models.py             │
│  │DetailScreen│   │    │                        │
│  └────────────┘   │    │                        │
└───────────────────┘    └────────────────────────┘
```

### 3.1 Layer Responsibilities

| Layer | Files | Responsibility |
|-------|-------|----------------|
| CLI | `cli.py` | Parse arguments, load config/inventory, launch app |
| Application | `app.py` | Textual App lifecycle, owns shared state (SSH backend) |
| UI | `screens/main.py`, `screens/detail.py` | Compose widgets, handle user input, trigger data fetches |
| Backend | `ssh.py` | All remote operations via asyncssh |
| Services | `services.py` | Glob pattern resolution against discovered systemd units |
| Data | `models.py` | Dataclass definitions for typed data flow |
| Config | `config.py`, `inventory.py` | Parse YAML and INI input files |

## 4. Data Models

```python
@dataclass
class ServiceConfig:
    name: str                         # systemd unit name (e.g. "nginx") or glob pattern (e.g. "docker-*")
    files: list[str] = []             # absolute paths on remote host
    commands: list[str] = []          # shell commands to execute on remote host

@dataclass
class Host:
    address: str                      # IP or hostname
    group: str                        # inventory group (e.g. "webservers")

@dataclass
class ServiceStatus:
    service: str                      # service name
    host: str                         # host address
    active: bool                      # True if systemctl exit code == 0
    status_output: str                # stdout from systemctl status
    error: str = ""                   # connection/execution error message
```

## 5. Input File Formats

### 5.1 Inventory File (INI)

Ansible-compatible INI format. Group headers are optional; ungrouped hosts are assigned to the `"ungrouped"` group.

```ini
[webservers]
192.168.1.10
192.168.1.11

[dbservers]
192.168.1.20
```

**Parsing rules:**
- Lines starting with `#` or `;` are comments.
- `[groupname]` sets the current group.
- First whitespace-delimited token on non-comment, non-group lines is taken as the host address.

### 5.2 Services Config (YAML)

```yaml
services:
  nginx:
    files:
      - /etc/nginx/nginx.conf
      - /var/log/nginx/error.log
    commands:
      - nginx -T
  postgresql:
    files:
      - /etc/postgresql/14/main/postgresql.conf
    commands:
      - pg_isready
  redis:
    commands:
      - redis-cli ping
  docker-*:
    commands:
      - docker stats --no-stream
```

**Structure:** Top-level `services` key maps service names to objects with optional `files` and `commands` lists. Service names may contain glob characters (`*`, `?`, `[`) to match multiple systemd units on each host. Matched services inherit the `files` and `commands` from their pattern entry. If a concrete service is matched by multiple patterns, the first match wins.

## 6. SSH Backend

### 6.1 Connection Management

- Uses `asyncssh` for non-blocking SSH operations.
- Reads `~/.ssh/config` if present for host-specific settings (username, port, key).
- Falls back to the current OS user if no SSH config username is set.
- Connections are stored in a `dict[str, SSHClientConnection]` keyed by host address.
- All hosts are connected concurrently via `asyncio.gather`.
- Host key verification is currently disabled (`known_hosts=None`).

### 6.2 Remote Operations

| Method | Remote Command | Purpose |
|--------|---------------|---------|
| `get_service_status(host, service)` | `systemctl status <service>` | Check if service is active (exit code 0) |
| `list_services(host)` | `systemctl list-units --type=service --all --no-legend --no-pager` | Discover all service unit names on a host (for glob resolution) |
| `get_journal(host, service, lines)` | `journalctl -u <service> --no-pager -n <lines>` | Retrieve recent journal entries |
| `read_file(host, path)` | `cat <path>` | Read a configuration/log file |
| `run_command(host, command)` | `<command>` | Execute arbitrary command |

All methods return string output and handle errors gracefully (return error message strings rather than raising).

### 6.3 Connection Lifecycle

1. **Startup:** `SSHBackend.connect()` called once from `MainScreen._fetch_statuses()`.
2. **Usage:** Connections reused for all subsequent status checks, journal fetches, file reads, and command executions.
3. **Shutdown:** `SSHBackend.close()` called from `App.action_quit()` and `App.on_unmount()`.

## 7. User Interface

Built on the [Textual](https://textual.textualize.io/) TUI framework.

### 7.1 Screen: Main Overview

**Purpose:** Display all service/host statuses at a glance.

**Layout:**
```
┌──────────────────────────────────────┐
│ Header: "System Controller"          │
├──────────────────────────────────────┤
│ DataTable                            │
│ ┌──────────┬──────────────┬────────┐ │
│ │ Service  │ Host         │ Status │ │
│ ├──────────┼──────────────┼────────┤ │
│ │ nginx    │ 192.168.1.10 │ ● active│ │
│ │ nginx    │ 192.168.1.11 │ ○ inact.│ │
│ │ postgres │ 192.168.1.20 │ ⚠ error│ │
│ └──────────┴──────────────┴────────┘ │
├──────────────────────────────────────┤
│ Footer: r=Refresh  q=Quit            │
└──────────────────────────────────────┘
```

**Status indicators:**
- `● active` (green) — service running
- `○ inactive` (yellow) — service stopped
- `⚠ <error>` (red) — connection or execution error

**Key bindings:**

| Key | Action |
|-----|--------|
| `r` | Manual refresh (re-connect and re-fetch) |
| `q` | Quit application |
| `Enter` | Open detail view for selected row |

**Behavior:**
- On mount: shows loading indicator, connects to all hosts, fetches all statuses concurrently.
- Auto-refresh timer fires every 30 seconds (re-fetches without reconnecting).
- Manual refresh (`r`) reconnects and re-fetches with a loading overlay.

### 7.2 Screen: Service Detail

**Purpose:** Show detailed information for a single service on a single host.

**Layout:**
```
┌──────────────────────────────────────┐
│ Header                               │
├──────────────────────────────────────┤
│   nginx @ 192.168.1.10               │
├──────────────────────────────────────┤
│ ┌─────────┬────────────┬───────────┐ │
│ │ Journal │ nginx.conf │ nginx     │ │  ← Tabs
│ └─────────┴────────────┴───────────┘ │
│ ┌──────────────────────────────────┐ │
│ │ (read-only TextArea with content)│ │
│ │                                  │ │
│ └──────────────────────────────────┘ │
├──────────────────────────────────────┤
│ Footer: Escape=Back                  │
└──────────────────────────────────────┘
```

**Tabs are generated dynamically:**
1. **Journal** — always present, shows `journalctl` output.
2. **File tabs** — one per entry in `ServiceConfig.files`, labeled with the basename.
3. **Command tabs** — one per entry in `ServiceConfig.commands`, labeled with the first word of the command.

**Key bindings:**

| Key | Action |
|-----|--------|
| `Escape` | Return to main screen |

**Behavior:**
- On mount: all data (journal, files, commands) fetched concurrently.
- Each tab shows a loading indicator until its data arrives, then swaps to a read-only TextArea.

## 8. Execution Flow

```
1. CLI: parse --inventory and --config arguments
2. CLI: load_config() → list[ServiceConfig]
3. CLI: load_inventory() → list[Host]
4. CLI: SystemControllerApp(services, hosts).run()
5. App: on_mount() → push MainScreen
6. MainScreen: on_mount() → start _fetch_statuses worker
7.   SSHBackend.connect() → concurrent SSH to all hosts
7a.  For each host: SSHBackend.list_services() → discover available units
7b.  For each host: resolve_services() → expand glob patterns against available units
8.   For each (resolved_service, host): SSHBackend.get_service_status()
9.   Populate DataTable with results
10.  Start 30s auto-refresh timer
11. [User selects a row]
12. MainScreen: push DetailScreen(service_config, host)
13. DetailScreen: on_mount() → start _fetch_all worker
14.   Concurrent: get_journal(), read_file()×N, run_command()×N
15.   Load results into TextArea widgets as they arrive
16. [User presses Escape]
17. DetailScreen: pop_screen() → return to MainScreen
18. [User presses q]
19. App: SSHBackend.close() → close all connections → exit
```

## 9. Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `textual` | >= 0.40.0 | TUI framework (widgets, screens, app lifecycle) |
| `asyncssh` | >= 2.14.0 | Async SSH client (connections, command execution) |
| `pyyaml` | >= 6.0 | YAML parsing for services configuration |

**Build system:** setuptools >= 68.0 with wheel.

**Python:** >= 3.10 (required for `list[str]` type hint syntax in dataclasses).

## 10. Entry Points

| Method | Command |
|--------|---------|
| Console script | `system-controller -i <inventory> -c <config>` |
| Module execution | `python -m system_controller.cli -i <inventory> -c <config>` |

## 11. Project Structure

```
system-controller/
├── pyproject.toml                    # Package metadata, dependencies, entry points
├── spec.md                           # Original requirements
├── services.yaml                     # Example services configuration
├── inventory.ini                     # Example host inventory
└── src/
    └── system_controller/
        ├── __init__.py
        ├── __main__.py               # Enables `python -m system_controller`
        ├── cli.py                    # Argument parsing, app bootstrap
        ├── app.py                    # Textual App subclass
        ├── models.py                 # ServiceConfig, Host, ServiceStatus
        ├── config.py                 # YAML config loader
        ├── inventory.py              # INI inventory parser
        ├── ssh.py                    # SSHBackend (asyncssh wrapper)
        ├── services.py              # Glob pattern resolution for service configs
        └── screens/
            ├── __init__.py
            ├── main.py               # MainScreen (status table)
            └── detail.py             # DetailScreen (tabbed detail view)
```

## 12. Known Limitations

1. **No host key verification** — `known_hosts=None` disables SSH host key checking. Suitable for trusted networks only.
2. **No authentication UI** — relies entirely on SSH agent or key-based auth configured in `~/.ssh/config`. No password prompt support.
3. **No per-group service mapping** — all services are checked on all hosts regardless of host group.
4. **No reconnection logic** — if a connection drops mid-session, the host shows errors until a manual refresh reconnects.
5. **No input validation** — malformed YAML or inventory files produce unhandled exceptions.
6. **No test suite** — no unit or integration tests exist yet.
7. **README references wrong project name** — header says "pcap-maker" instead of "system-controller".
