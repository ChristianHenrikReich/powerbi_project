"""Load the environment/workspace configuration shared by setup and deployment."""

from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import UUID

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "semantic_model_solution.yml"
ENVIRONMENTS = ("dev", "tst", "prd")
WORKSPACES = ("reporting",)


def guid(value: str, label: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError(f"{label} must be a non-empty GUID.") from error
    if parsed.int == 0:
        raise ValueError(f"{label} must not be the zero GUID.")
    return str(parsed)


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"Expected a mapping in {path}.")
    if not isinstance(config.get("solution_name"), str) or not re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9_-]*", config["solution_name"]
    ):
        raise ValueError("solution_name must contain only letters, numbers, underscores, or hyphens.")
    if not isinstance(config.get("workspaces"), dict):
        raise ValueError("Configuration requires a workspaces mapping.")
    aliases = config.get("alias", {})
    if not isinstance(aliases, dict) or not all(isinstance(v, str) for v in aliases.values()):
        raise ValueError("alias must map names to string values.")
    return config


def workspace_settings(config: dict, workspace: str, environment: str) -> dict:
    if workspace not in WORKSPACES or environment not in ENVIRONMENTS:
        raise ValueError(f"Unsupported workspace/environment: {workspace}/{environment}.")
    workspace_config = config["workspaces"].get(workspace)
    if not isinstance(workspace_config, dict):
        raise ValueError(f"Missing workspace configuration: {workspace}.")
    entry = workspace_config.get(environment)
    if not isinstance(entry, dict):
        raise ValueError(f"Missing workspace configuration: {workspace}/{environment}.")
    aliases = config.get("alias", {})
    settings = {}
    for key in ("id", "capacity"):
        value = entry.get(key, "")
        if not isinstance(value, str):
            raise ValueError(f"{workspace}/{environment}/{key} must be a string.")
        visited = set()
        while value in aliases:
            if value in visited:
                raise ValueError(f"Circular alias reference: {value}.")
            visited.add(value)
            value = aliases[value]
        variable = f"{workspace}_{environment}_{'workspace_id' if key == 'id' else 'capacity_id'}".upper()
        override = os.getenv(variable)
        if override is not None and override.strip():
            value = override.strip()
        settings[key] = guid(value, variable) if value else ""
    settings["name"] = f"{config['solution_name']}-{workspace}-{environment}"
    return settings


def get_workspace_id(config: dict, workspace: str, environment: str) -> str:
    settings = workspace_settings(config, workspace, environment)
    if not settings["id"]:
        raise ValueError(
            f"No workspace ID configured for {workspace}/{environment}. "
            "Run setup_workspaces.py first, or configure the workspace ID."
        )
    return settings["id"]
