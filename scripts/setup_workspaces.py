"""Resolve or create reporting workspaces for one environment or all environments."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

if __package__:
    from .config import CONFIG_PATH, ENVIRONMENTS, WORKSPACES, guid, load_config, workspace_settings
    from .fabric_client import FABRIC_ROOT, FabricClient
else:
    from config import CONFIG_PATH, ENVIRONMENTS, WORKSPACES, guid, load_config, workspace_settings
    from fabric_client import FABRIC_ROOT, FabricClient


def setup(config: dict, workspace: str, environment: str, client: FabricClient, *, dry_run=False) -> str:
    settings = workspace_settings(config, workspace, environment)
    if settings["id"]:
        remote = client.request("GET", f"{FABRIC_ROOT}/workspaces/{settings['id']}").json()
        workspace_id = guid(remote["id"], "Resolved workspace ID")
        print(f"Using configured workspace: {remote['displayName']} ({workspace_id})")
    else:
        matches = [
            item for item in client.list_all(f"{FABRIC_ROOT}/workspaces")
            if item["displayName"] == settings["name"]
        ]
        if len(matches) > 1:
            raise ValueError(f"Multiple accessible workspaces named {settings['name']}; configure an ID.")
        if matches:
            workspace_id = guid(matches[0]["id"], "Resolved workspace ID")
            print(f"Found workspace: {settings['name']} ({workspace_id})")
        else:
            if not settings["capacity"]:
                raise ValueError(
                    f"Creating {settings['name']} requires a capacity ID in configuration or "
                    f"{workspace.upper()}_{environment.upper()}_CAPACITY_ID."
                )
            if dry_run:
                print(f"Would create workspace: {settings['name']}")
                return ""
            remote = client.create_workspace(settings["name"], settings["capacity"])
            workspace_id = guid(remote["id"], "Created workspace ID")
            print(f"Created workspace: {settings['name']} ({workspace_id})")
    if not dry_run:
        config["workspaces"][workspace][environment]["id"] = workspace_id
    return workspace_id


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", choices=WORKSPACES, default="reporting")
    parser.add_argument("--environment", choices=(*ENVIRONMENTS, "all"), required=True)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output", type=Path, help="Write resolved config here instead of changing the input.")
    parser.add_argument("--dry-run", action="store_true", help="Read APIs but do not create or write anything.")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    client = FabricClient()
    environments = ENVIRONMENTS if args.environment == "all" else (args.environment,)
    for environment in environments:
        setup(config, args.workspace, environment, client, dry_run=args.dry_run)
    if not args.dry_run:
        output = args.output or args.config
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        print(f"Workspace configuration written to {output}")


if __name__ == "__main__":
    main()
