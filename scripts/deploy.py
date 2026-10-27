"""Publish the semantic model and its consuming report to one environment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from azure.identity import AzureCliCredential
from fabric_cicd import FabricWorkspace, publish_all_items, unpublish_all_orphan_items

if __package__:
    from .config import CONFIG_PATH, ENVIRONMENTS, REPO_ROOT, WORKSPACES, get_workspace_id, load_config
    from .fabric_client import FABRIC_ROOT, POWERBI_ROOT, FabricClient
else:
    from config import CONFIG_PATH, ENVIRONMENTS, REPO_ROOT, WORKSPACES, get_workspace_id, load_config
    from fabric_client import FABRIC_ROOT, POWERBI_ROOT, FabricClient

ITEM_TYPES = ["SemanticModel", "Report"]


def verify_deployment(client: FabricClient, workspace_id: str, directory: Path) -> list[str]:
    items = client.list_all(f"{FABRIC_ROOT}/workspaces/{workspace_id}/items")
    item_ids = {}
    for platform_path in directory.glob("*/.platform"):
        metadata = json.loads(platform_path.read_text(encoding="utf-8"))["metadata"]
        kind, name = metadata["type"], metadata["displayName"]
        if kind not in ITEM_TYPES:
            continue
        matches = [item for item in items if item["type"] == kind and item["displayName"] == name]
        if len(matches) != 1:
            raise RuntimeError(f"Expected exactly one deployed {kind} named {name}; found {len(matches)}.")
        item_ids[platform_path.parent.resolve()] = matches[0]["id"]
    if not item_ids:
        raise RuntimeError("No semantic model or report items found for readback verification.")
    for definition in directory.glob("*.Report/definition.pbir"):
        report_id = item_ids[definition.parent.resolve()]
        binding = json.loads(definition.read_text(encoding="utf-8"))["datasetReference"]["byPath"]["path"]
        model_id = item_ids[(definition.parent / binding).resolve()]
        report = client.request("GET", f"{POWERBI_ROOT}/groups/{workspace_id}/reports/{report_id}").json()
        if report.get("datasetId") != model_id:
            raise RuntimeError(f"Report {report_id} is not bound to this environment's semantic model.")
        print(f"Verified report {report_id} -> model {model_id}")
    return [
        item_ids[path.parent.resolve()]
        for path in directory.glob("*.SemanticModel/.platform")
    ]


def deploy(workspace: str, environment: str, config: dict, *, refresh=False, unpublish_orphans=False):
    workspace_id = get_workspace_id(config, workspace, environment)
    directory = REPO_ROOT / "solution" / workspace
    if not directory.is_dir():
        raise ValueError(f"Workspace folder not found: {directory}")
    credential = AzureCliCredential()
    target = FabricWorkspace(
        workspace_id=workspace_id,
        environment=environment.upper(),
        repository_directory=str(directory),
        item_type_in_scope=ITEM_TYPES,
        token_credential=credential,
    )
    publish_all_items(target)
    client = FabricClient(credential)
    model_ids = verify_deployment(client, workspace_id, directory)
    if refresh:
        for model_id in model_ids:
            client.refresh_model(workspace_id, model_id)
    if unpublish_orphans:
        unpublish_all_orphan_items(target)
    print(f"Deployed {workspace} to {environment.upper()} ({workspace_id})")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", choices=WORKSPACES, default="reporting")
    parser.add_argument("--environment", choices=ENVIRONMENTS, required=True)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--refresh", action="store_true", help="Run and await a full enhanced model refresh.")
    parser.add_argument(
        "--unpublish-orphans", action="store_true",
        help="DESTRUCTIVE: remove workspace SemanticModel/Report items absent from this folder.",
    )
    args = parser.parse_args(argv)
    deploy(
        args.workspace, args.environment, load_config(args.config),
        refresh=args.refresh, unpublish_orphans=args.unpublish_orphans,
    )


if __name__ == "__main__":
    main()
