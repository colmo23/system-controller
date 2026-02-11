# system-controller

A terminal user interface (TUI) for monitoring systemd services across remote hosts via SSH.

## Install

Setup for development environment:
```
python3 -m venv venv
source venv/bin/activate
pip install -e .[dev]
```

For a production environment:
```
pip install .
```

## Usage

The application requires two input files:

- **Inventory file** — an Ansible-style INI file listing target hosts
- **Services config** — a YAML file defining which systemd services to monitor

Run with the installed console script:
```
system-controller -i inventory.ini -c services.yaml
```

Or run as a Python module:
```
python3 -m system_controller.cli -i inventory.ini -c services.yaml
```

### Keyboard Controls

**Main screen:**

| Key     | Action                          |
|---------|---------------------------------|
| `Enter` | View details for selected service |
| `r`     | Refresh all statuses            |
| `q`     | Quit                            |

**Detail screen:**

| Key      | Action             |
|----------|--------------------|
| `Escape` | Back to main screen |

### SSH Authentication

The application uses your existing SSH configuration (`~/.ssh/config`) and SSH agent for authentication. Ensure you can `ssh` to each host in your inventory without a password prompt before running.

### Example Files

`inventory.ini`:
```ini
[webservers]
192.168.1.10
192.168.1.11

[dbservers]
192.168.1.20
```

`services.yaml`:
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

Service names support glob patterns (`*`, `?`, `[`). On each host, patterns are matched against the available systemd units and expanded into individual rows. For example, `docker-*` on a host running `docker-api` and `docker-worker` produces two rows, each inheriting the configured `commands` and `files` from the pattern entry.

## Unittests

```
pytest .
```

## Code reformatting

```
autopep8 --in-place --aggressive --aggressive src/system_controller/*py
```

```
black src/system_controller
```

## Code style

```
flake8 src/system_controller
```

```
pylint src/system_controller/*py
```

## CI tests

```
pip3 install tox
tox
```
