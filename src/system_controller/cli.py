import argparse
import logging
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="system-controller",
        description="TUI for monitoring systemd services across remote hosts",
    )
    parser.add_argument(
        "--inventory", "-i",
        required=True,
        help="Path to Ansible inventory file (INI format)",
    )
    parser.add_argument(
        "--config", "-c",
        required=True,
        help="Path to services YAML config file",
    )
    parser.add_argument(
        "--log", "-l",
        default=None,
        help="Path to log file (if omitted, logging is disabled)",
    )
    args = parser.parse_args()

    if args.log:
        logging.basicConfig(
            filename=args.log,
            level=logging.DEBUG,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )

    from system_controller.config import load_config
    from system_controller.inventory import load_inventory
    from system_controller.app import SystemControllerApp

    services = load_config(args.config)
    hosts = load_inventory(args.inventory)

    app = SystemControllerApp(services=services, hosts=hosts)
    app.run()
