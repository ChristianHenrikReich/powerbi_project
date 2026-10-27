from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
import yaml
from azure.core.credentials import AccessToken
from azure.identity import AzureCliCredential
from fabric_cicd import FabricWorkspace
from fabric_cicd._items._report import func_process_file

from scripts import config, deploy, setup_workspaces
from scripts.fabric_client import FABRIC_ROOT, POWERBI_ROOT, FabricClient
from scripts.setup_workspaces import setup

WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"
CAPACITY_ID = "22222222-2222-4222-8222-222222222222"
MODEL_ID = "33333333-3333-4333-8333-333333333333"
REPORT_ID = "44444444-4444-4444-8444-444444444444"
REFRESH_ID = "55555555-5555-4555-8555-555555555555"
DIRECTORY = config.REPO_ROOT / "solution" / "reporting"


def sample_config():
    return {
        "solution_name": "sales",
        "alias": {"reporting_capacity": ""},
        "workspaces": {
            "reporting": {
                environment: {"id": "", "capacity": "reporting_capacity"}
                for environment in config.ENVIRONMENTS
            }
        },
    }


def response(body=None, status=200, headers=None):
    result = Mock()
    result.json.return_value = body
    result.status_code = status
    result.headers = headers or {}
    return result


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.config = sample_config()

    def test_workspace_names_and_unconfigured_ids(self):
        for environment in config.ENVIRONMENTS:
            settings = config.workspace_settings(self.config, "reporting", environment)
            self.assertEqual(settings["name"], f"sales-reporting-{environment}")
            self.assertEqual(settings["id"], "")
            self.assertEqual(settings["capacity"], "")

    def test_missing_workspace_id_is_actionable(self):
        with self.assertRaisesRegex(ValueError, "setup_workspaces"):
            config.get_workspace_id(self.config, "reporting", "dev")

    def test_environment_overrides_configuration(self):
        self.config["workspaces"]["reporting"]["dev"]["id"] = MODEL_ID
        with patch.dict(os.environ, {"REPORTING_DEV_WORKSPACE_ID": WORKSPACE_ID}):
            self.assertEqual(config.get_workspace_id(self.config, "reporting", "dev"), WORKSPACE_ID)

    def test_empty_github_variable_does_not_erase_configured_id(self):
        self.config["workspaces"]["reporting"]["dev"]["id"] = WORKSPACE_ID
        with patch.dict(os.environ, {"REPORTING_DEV_WORKSPACE_ID": ""}):
            self.assertEqual(config.get_workspace_id(self.config, "reporting", "dev"), WORKSPACE_ID)

    def test_capacity_aliases_can_be_chained(self):
        self.config["alias"].update(reporting_capacity="shared", shared=CAPACITY_ID)
        self.assertEqual(config.workspace_settings(self.config, "reporting", "dev")["capacity"], CAPACITY_ID)

    def test_circular_alias_is_rejected(self):
        self.config["alias"].update(reporting_capacity="shared", shared="reporting_capacity")
        with self.assertRaisesRegex(ValueError, "Circular alias"):
            config.workspace_settings(self.config, "reporting", "dev")

    def test_invalid_guid_and_zero_guid_are_rejected(self):
        for value in ("not-a-guid", "00000000-0000-0000-0000-000000000000"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                config.guid(value, "Test ID")

    def test_invalid_environment_and_workspace_shape_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            config.workspace_settings(self.config, "reporting", "prod")
        self.config["workspaces"]["reporting"] = []
        with self.assertRaisesRegex(ValueError, "Missing workspace"):
            config.workspace_settings(self.config, "reporting", "dev")

    def test_invalid_config_file_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "config.yml"
            for content in ("[]", "solution_name: invalid/name\nworkspaces: {}", "solution_name: sales"):
                file.write_text(content, encoding="utf-8")
                with self.subTest(content=content), self.assertRaises(ValueError):
                    config.load_config(file)

    def test_valid_config_file_is_loaded_without_changing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "config.yml"
            file.write_text(yaml.safe_dump(self.config), encoding="utf-8")
            self.assertEqual(config.load_config(file), self.config)


class WorkspaceSetupTests(unittest.TestCase):
    def setUp(self):
        self.config = sample_config()
        self.client = Mock()
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_existing_workspace_is_resolved_without_creation(self):
        self.client.list_all.return_value = [{"displayName": "sales-reporting-dev", "id": WORKSPACE_ID}]
        setup(self.config, "reporting", "dev", self.client)
        self.assertEqual(self.config["workspaces"]["reporting"]["dev"]["id"], WORKSPACE_ID)
        self.assertEqual(self.config["workspaces"]["reporting"]["tst"]["id"], "")
        self.client.create_workspace.assert_not_called()

    def test_configured_workspace_id_is_used_even_if_name_is_different(self):
        self.config["workspaces"]["reporting"]["dev"]["id"] = WORKSPACE_ID
        self.client.request.return_value = response({"id": WORKSPACE_ID, "displayName": "Existing BI"})
        self.assertEqual(setup(self.config, "reporting", "dev", self.client), WORKSPACE_ID)
        self.client.list_all.assert_not_called()

    def test_ambiguous_names_fail_without_writes(self):
        self.client.list_all.return_value = [
            {"displayName": "sales-reporting-dev", "id": WORKSPACE_ID},
            {"displayName": "sales-reporting-dev", "id": MODEL_ID},
        ]
        with self.assertRaisesRegex(ValueError, "Multiple accessible"):
            setup(self.config, "reporting", "dev", self.client)
        self.client.create_workspace.assert_not_called()

    def test_creation_requires_capacity(self):
        self.client.list_all.return_value = []
        with self.assertRaisesRegex(ValueError, "requires a capacity"):
            setup(self.config, "reporting", "dev", self.client)
        self.client.create_workspace.assert_not_called()

    def test_creation_uses_selected_environment(self):
        self.config["alias"]["reporting_capacity"] = CAPACITY_ID
        self.client.list_all.return_value = []
        self.client.create_workspace.return_value = {"id": WORKSPACE_ID}
        setup(self.config, "reporting", "tst", self.client)
        self.client.create_workspace.assert_called_once_with("sales-reporting-tst", CAPACITY_ID)
        self.assertEqual(self.config["workspaces"]["reporting"]["dev"]["id"], "")

    def test_dry_run_does_not_mutate_configuration_or_create(self):
        self.config["alias"]["reporting_capacity"] = CAPACITY_ID
        before = copy.deepcopy(self.config)
        self.client.list_all.return_value = []
        setup(self.config, "reporting", "prd", self.client, dry_run=True)
        self.assertEqual(self.config, before)
        self.client.create_workspace.assert_not_called()

    def test_all_environments_reuse_existing_and_create_only_missing_workspaces(self):
        self.config["alias"]["reporting_capacity"] = CAPACITY_ID
        self.config["workspaces"]["reporting"]["dev"]["id"] = WORKSPACE_ID
        self.client.request.return_value = response({
            "id": WORKSPACE_ID, "displayName": "Existing BI",
        })
        self.client.list_all.return_value = [{
            "displayName": "sales-reporting-tst", "id": MODEL_ID,
        }]
        self.client.create_workspace.return_value = {"id": REPORT_ID}
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "config.yml"
            output = Path(directory) / ".deploy" / "resolved.yml"
            source.write_text(yaml.safe_dump(self.config), encoding="utf-8")
            original = source.read_bytes()
            with patch.object(setup_workspaces, "FabricClient", return_value=self.client):
                setup_workspaces.main([
                    "--environment", "all", "--config", str(source), "--output", str(output),
                ])
            resolved = config.load_config(output)
            self.assertEqual(
                [resolved["workspaces"]["reporting"][env]["id"] for env in config.ENVIRONMENTS],
                [WORKSPACE_ID, MODEL_ID, REPORT_ID],
            )
            self.assertEqual(source.read_bytes(), original)
        self.client.create_workspace.assert_called_once_with("sales-reporting-prd", CAPACITY_ID)
        self.client.request.assert_called_once_with("GET", f"{FABRIC_ROOT}/workspaces/{WORKSPACE_ID}")

    def test_all_environments_dry_run_does_not_create_or_write(self):
        self.config["alias"]["reporting_capacity"] = CAPACITY_ID
        self.client.list_all.return_value = []
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "config.yml"
            output = Path(directory) / "resolved.yml"
            source.write_text(yaml.safe_dump(self.config), encoding="utf-8")
            original = source.read_bytes()
            with patch.object(setup_workspaces, "FabricClient", return_value=self.client):
                setup_workspaces.main([
                    "--environment", "all", "--config", str(source),
                    "--output", str(output), "--dry-run",
                ])
            self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), original)
        self.assertEqual(self.client.list_all.call_count, len(config.ENVIRONMENTS))
        self.client.create_workspace.assert_not_called()

    def test_all_environments_setup_failure_propagates_without_writing_config(self):
        self.config["workspaces"]["reporting"]["dev"]["id"] = WORKSPACE_ID
        self.client.request.return_value = response({
            "id": WORKSPACE_ID, "displayName": "Existing BI",
        })
        self.client.list_all.side_effect = requests.HTTPError("403 Forbidden")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "config.yml"
            output = Path(directory) / "resolved.yml"
            source.write_text(yaml.safe_dump(self.config), encoding="utf-8")
            original = source.read_bytes()
            with (
                patch.object(setup_workspaces, "FabricClient", return_value=self.client),
                self.assertRaises(requests.HTTPError),
            ):
                setup_workspaces.main([
                    "--environment", "all", "--config", str(source), "--output", str(output),
                ])
            self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), original)
        self.client.create_workspace.assert_not_called()
        self.client.list_all.assert_called_once()

    def test_cli_selected_environment_does_not_resolve_other_environments(self):
        self.config["workspaces"]["reporting"]["prd"]["id"] = REPORT_ID
        self.client.request.return_value = response({
            "id": REPORT_ID, "displayName": "Production BI",
        })
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "config.yml"
            source.write_text(yaml.safe_dump(self.config), encoding="utf-8")
            with patch.object(setup_workspaces, "FabricClient", return_value=self.client):
                setup_workspaces.main(["--environment", "prd", "--config", str(source)])
            self.assertEqual(config.load_config(source), self.config)
        self.client.request.assert_called_once_with("GET", f"{FABRIC_ROOT}/workspaces/{REPORT_ID}")
        self.client.list_all.assert_not_called()
        self.client.create_workspace.assert_not_called()


class RestClientTests(unittest.TestCase):
    def setUp(self):
        self.credential = Mock()
        self.credential.get_token.return_value = SimpleNamespace(token="unit-test-token")
        self.session = Mock()
        self.session.request.return_value = response({})
        self.client = FabricClient(self.credential, self.session)

    def test_audiences_telemetry_and_request_timeout(self):
        self.client.request("GET", f"{FABRIC_ROOT}/workspaces")
        self.credential.get_token.assert_called_with("https://api.fabric.microsoft.com/.default")
        kwargs = self.session.request.call_args.kwargs
        self.assertEqual(kwargs["headers"]["x-ms-fabric-skill"], "semantic-model-authoring")
        self.assertEqual(kwargs["timeout"], 60)
        self.assertFalse(kwargs["allow_redirects"])
        self.client.request("GET", f"{POWERBI_ROOT}/groups")
        self.credential.get_token.assert_called_with("https://analysis.windows.net/powerbi/api/.default")

    def test_untrusted_or_non_https_api_is_rejected_before_auth(self):
        for url in ("http://api.fabric.microsoft.com/v1", "https://example.com/v1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.client.request("GET", url)
        self.credential.get_token.assert_not_called()

    def test_api_errors_propagate(self):
        self.session.request.return_value.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
        with self.assertRaises(requests.HTTPError):
            self.client.request("GET", f"{FABRIC_ROOT}/workspaces")

    def test_pagination_collects_all_pages(self):
        self.session.request.side_effect = [
            response({"value": [1], "continuationUri": f"{FABRIC_ROOT}/workspaces?next=1"}),
            response({"value": [2]}),
        ]
        self.assertEqual(self.client.list_all(f"{FABRIC_ROOT}/workspaces"), [1, 2])

    def test_pagination_rejects_cycles_and_foreign_hosts(self):
        url = f"{FABRIC_ROOT}/workspaces"
        for continuation in (url, "https://example.com/token"):
            self.session.request.return_value = response({"value": [], "continuationUri": continuation})
            with self.subTest(continuation=continuation), self.assertRaises(ValueError):
                self.client.list_all(url)

    def test_refresh_awaits_completion(self):
        location = f"{POWERBI_ROOT}/groups/{WORKSPACE_ID}/datasets/{MODEL_ID}/refreshes/{REFRESH_ID}"
        self.session.request.side_effect = [
            response(status=202, headers={"Location": location}),
            response({"status": "InProgress"}, status=202),
            response({"status": "Completed"}),
        ]
        with patch("scripts.fabric_client.time.sleep"):
            self.client.refresh_model(WORKSPACE_ID, MODEL_ID)
        self.assertEqual(self.session.request.call_count, 3)

    def test_refresh_failure_does_not_retry_write(self):
        location = f"{POWERBI_ROOT}/groups/{WORKSPACE_ID}/datasets/{MODEL_ID}/refreshes/{REFRESH_ID}"
        self.session.request.side_effect = [
            response(status=202, headers={"Location": location}), response({"status": "Failed"}),
        ]
        with self.assertRaisesRegex(RuntimeError, "credentials"):
            self.client.refresh_model(WORKSPACE_ID, MODEL_ID)
        self.assertEqual(self.session.request.call_count, 2)

    def test_refresh_requires_valid_location(self):
        for headers in ({}, {"Location": "https://example.com/refresh"}):
            self.session.request.return_value = response(status=202, headers=headers)
            with self.subTest(headers=headers), self.assertRaises((ValueError, RuntimeError)):
                self.client.refresh_model(WORKSPACE_ID, MODEL_ID)

    def test_request_id_header_uses_canonical_api_not_regional_location(self):
        self.session.request.side_effect = [
            response(status=202, headers={
                "x-ms-request-id": REFRESH_ID,
                "Location": f"https://wabi-region.analysis.windows.net/refreshes/{REFRESH_ID}",
            }),
            response({"status": "Completed"}),
        ]
        self.client.refresh_model(WORKSPACE_ID, MODEL_ID)
        self.assertEqual(self.session.request.call_count, 2)
        self.assertEqual(
            self.session.request.call_args.args,
            ("GET", f"{POWERBI_ROOT}/groups/{WORKSPACE_ID}/datasets/{MODEL_ID}/refreshes/{REFRESH_ID}"),
        )

    def test_location_id_supports_regional_relative_and_case_variations(self):
        for location in (
            f"https://wabi-region.analysis.windows.net/refreshes/{REFRESH_ID}",
            f"/v1.0/myorg/groups/{WORKSPACE_ID}/datasets/{MODEL_ID}/refreshes/{REFRESH_ID}",
            f"{POWERBI_ROOT}/groups/{WORKSPACE_ID.upper()}/datasets/{MODEL_ID.upper()}/refreshes/{REFRESH_ID}",
        ):
            with self.subTest(location=location):
                self.session.request.reset_mock()
                self.session.request.side_effect = [
                    response(status=202, headers={"Location": location}),
                    response({"status": "Completed"}),
                ]
                self.client.refresh_model(WORKSPACE_ID, MODEL_ID)
                self.assertEqual(
                    self.session.request.call_args.args,
                    ("GET", f"{POWERBI_ROOT}/groups/{WORKSPACE_ID}/datasets/{MODEL_ID}/refreshes/{REFRESH_ID}"),
                )

    def test_request_id_header_is_sufficient_without_location(self):
        self.session.request.side_effect = [
            response(status=202, headers={"x-ms-request-id": REFRESH_ID}),
            response({"status": "Completed"}),
        ]
        self.client.refresh_model(WORKSPACE_ID, MODEL_ID)
        self.assertEqual(self.session.request.call_count, 2)

    def test_existing_refresh_can_be_polled_without_resubmitting(self):
        self.session.request.return_value = response({"status": "Completed"})
        self.client.wait_for_refresh(WORKSPACE_ID, MODEL_ID, REFRESH_ID)
        self.session.request.assert_called_once()
        self.assertEqual(self.session.request.call_args.args[0], "GET")

    def test_invalid_operation_ids_never_reach_the_api(self):
        for value in ("not-a-guid", "00000000-0000-0000-0000-000000000000", "../different-operation"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.client.wait_for_refresh(WORKSPACE_ID, MODEL_ID, value)
        self.session.request.assert_not_called()

    def test_refresh_polling_timeout_is_reported_without_resubmission(self):
        with self.assertRaisesRegex(TimeoutError, "exceeded"):
            self.client.wait_for_refresh(WORKSPACE_ID, MODEL_ID, REFRESH_ID, timeout=0)
        self.session.request.assert_not_called()


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.list_all.return_value = [
            {"type": "SemanticModel", "displayName": "Sales", "id": MODEL_ID},
            {"type": "Report", "displayName": "Sales", "id": REPORT_ID},
        ]
        self.client.request.return_value = response({"datasetId": MODEL_ID})

    def test_environment_model_binding_is_verified(self):
        self.assertEqual(deploy.verify_deployment(self.client, WORKSPACE_ID, DIRECTORY), [MODEL_ID])
        self.client.request.assert_called_once_with(
            "GET", f"{POWERBI_ROOT}/groups/{WORKSPACE_ID}/reports/{REPORT_ID}"
        )

    def test_wrong_report_binding_fails(self):
        self.client.request.return_value = response({"datasetId": "different-model"})
        with self.assertRaisesRegex(RuntimeError, "not bound"):
            deploy.verify_deployment(self.client, WORKSPACE_ID, DIRECTORY)

    def test_missing_or_duplicate_deployed_items_fail(self):
        for items in ([], self.client.list_all.return_value * 2):
            self.client.list_all.return_value = items
            with self.subTest(items=items), self.assertRaisesRegex(RuntimeError, "exactly one"):
                deploy.verify_deployment(self.client, WORKSPACE_ID, DIRECTORY)

    def test_publish_scope_and_safe_orphan_default(self):
        settings = sample_config()
        settings["workspaces"]["reporting"]["dev"]["id"] = WORKSPACE_ID
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(deploy, "AzureCliCredential"),
            patch.object(deploy, "FabricWorkspace") as workspace,
            patch.object(deploy, "publish_all_items") as publish,
            patch.object(deploy, "unpublish_all_orphan_items") as unpublish,
            patch.object(deploy, "FabricClient", return_value=self.client),
        ):
            deploy.deploy("reporting", "dev", settings, refresh=True)
            self.assertEqual(workspace.call_args.kwargs["item_type_in_scope"], ["SemanticModel", "Report"])
            self.assertEqual(workspace.call_args.kwargs["environment"], "DEV")
            publish.assert_called_once()
            unpublish.assert_not_called()
            self.client.refresh_model.assert_called_once_with(WORKSPACE_ID, MODEL_ID)


class ProjectStructureTests(unittest.TestCase):
    def test_project_points_to_report_and_local_model(self):
        project = json.loads((DIRECTORY / "Sales.pbip").read_text(encoding="utf-8"))
        report_dir = DIRECTORY / project["artifacts"][0]["report"]["path"]
        report = json.loads((report_dir / "definition.pbir").read_text(encoding="utf-8"))
        model = (report_dir / report["datasetReference"]["byPath"]["path"]).resolve()
        self.assertEqual(model, (DIRECTORY / "Sales.SemanticModel").resolve())
        for parts in (
            ("database.tmdl",), ("model.tmdl",), ("relationships.tmdl",),
            ("tables", "Product.tmdl"), ("tables", "Sales.tmdl"),
        ):
            self.assertTrue((model / "definition").joinpath(*parts).is_file(), parts)
        self.assertTrue((model / "definition.pbism").is_file())

    def test_platform_ids_are_unique_and_item_types_are_scoped(self):
        platforms = [json.loads(p.read_text(encoding="utf-8")) for p in DIRECTORY.glob("*/.platform")]
        self.assertEqual({p["metadata"]["type"] for p in platforms}, set(deploy.ITEM_TYPES))
        ids = [config.guid(p["config"]["logicalId"], "logicalId") for p in platforms]
        self.assertEqual(len(ids), len(set(ids)))

    def test_page_and_visual_count_bounds_and_ids(self):
        pages_root = DIRECTORY / "Sales.Report" / "definition" / "pages"
        metadata = json.loads((pages_root / "pages.json").read_text(encoding="utf-8"))
        self.assertEqual(len(metadata["pageOrder"]), 1)
        page_dir = pages_root / metadata["pageOrder"][0]
        page = json.loads((page_dir / "page.json").read_text(encoding="utf-8"))
        self.assertEqual((page["width"], page["height"]), (1920, 1080))
        visuals = [json.loads(p.read_text(encoding="utf-8")) for p in page_dir.glob("visuals/*/visual.json")]
        self.assertEqual(len(visuals), 6)
        self.assertEqual(len({v["name"] for v in visuals}), 6)
        for visual in visuals:
            box = visual["position"]
            self.assertGreater(box["width"], 0)
            self.assertGreater(box["height"], 0)
            self.assertGreaterEqual(box["x"], 0)
            self.assertGreaterEqual(box["y"], 0)
            self.assertLessEqual(box["x"] + box["width"], page["width"])
            self.assertLessEqual(box["y"] + box["height"], page["height"])

    def test_ci_octopus_merges_open_prs_and_deploys_only_tst(self):
        workflow = config.REPO_ROOT / ".github" / "workflows" / "pr-octopus-tst.yml"
        data = yaml.load(workflow.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        self.assertEqual(set(data["on"]), {"pull_request"})
        self.assertEqual(
            set(data["on"]["pull_request"]["types"]),
            {"opened", "reopened", "synchronize", "closed"},
        )
        self.assertEqual(set(data["jobs"]), {"octopus_merge", "deploy_tst"})
        self.assertEqual(data["jobs"]["deploy_tst"]["needs"], "octopus_merge")
        commands = "\n".join(
            step["run"] for step in data["jobs"]["deploy_tst"]["steps"] if "run" in step
        )
        self.assertIn("python -m unittest discover -s tests", commands)
        self.assertIn("npm run validate:report", commands)
        validation = commands.index("npm run validate:report")
        self.assertLess(validation, commands.index("scripts.setup_workspaces"))
        self.assertLess(validation, commands.index("scripts.deploy"))
        self.assertIn("--environment tst", commands)
        for other in ("dev", "prd", "all"):
            self.assertNotIn(f"--environment {other}", commands)

    def test_cd_only_runs_after_a_main_pull_request_is_merged(self):
        workflow = config.REPO_ROOT / ".github" / "workflows" / "deploy-fabric.yml"
        data = yaml.load(workflow.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        self.assertEqual(set(data["on"]), {"pull_request_target"})
        self.assertEqual(data["on"]["pull_request_target"], {
            "branches": ["main"], "types": ["closed"],
        })
        self.assertEqual(data["permissions"], {"contents": "read"})
        self.assertEqual(set(data["jobs"]), {"deploy"})
        job = data["jobs"]["deploy"]
        self.assertEqual(job["if"], "github.event.pull_request.merged == true")
        self.assertNotIn("needs", job)
        checkout = next(step for step in job["steps"] if step.get("uses") == "actions/checkout@v4")
        self.assertEqual(
            checkout["with"]["ref"], "${{ github.event.pull_request.merge_commit_sha }}"
        )
        self.assertEqual(checkout["with"]["persist-credentials"], "false")
        commands = "\n".join(step["run"] for step in job["steps"] if "run" in step)
        for validation in ("unittest", "validate:report", "setup-node", "npm ci"):
            self.assertNotIn(validation, commands)
        self.assertEqual(job["environment"]["name"], "fabric-prd")
        self.assertEqual(job["concurrency"]["group"], "fabric-reporting-prd")
        self.assertEqual(job["concurrency"]["cancel-in-progress"], "false")
        self.assertEqual(job["permissions"]["id-token"], "write")

    def test_workflow_provisions_all_workspaces_but_only_publishes_prd(self):
        workflow = config.REPO_ROOT / ".github" / "workflows" / "deploy-fabric.yml"
        data = yaml.load(workflow.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        job = data["jobs"]["deploy"]
        commands = [step["run"] for step in job["steps"] if "run" in step]
        setup_commands = [command for command in commands if "scripts.setup_workspaces" in command]
        deploy_commands = [command for command in commands if "scripts.deploy" in command]
        self.assertEqual(len(setup_commands), 1)
        self.assertEqual(len(deploy_commands), 1)
        self.assertIn("--environment all", setup_commands[0])
        self.assertIn(r"--output .deploy\resolved-solution.yml", setup_commands[0])
        self.assertIn("--environment prd", deploy_commands[0])
        self.assertIn(r"--config .deploy\resolved-solution.yml", deploy_commands[0])
        self.assertIn("--refresh", deploy_commands[0])
        self.assertLess(commands.index(setup_commands[0]), commands.index(deploy_commands[0]))
        for environment in ("dev", "tst"):
            self.assertNotIn(f"--environment {environment}", deploy_commands[0])
            self.assertEqual(
                job["env"][f"REPORTING_{environment.upper()}_WORKSPACE_ID"],
                "${{ vars.REPORTING_" + environment.upper() + "_WORKSPACE_ID }}",
            )


class FabricCicdIntegrationTests(unittest.TestCase):
    def test_pinned_library_accepts_parameters_and_rebinds_report(self):
        with patch.object(
            AzureCliCredential, "get_token", return_value=AccessToken("unit-test-token", 4102444800)
        ):
            workspace = FabricWorkspace(
                workspace_id=WORKSPACE_ID,
                environment="DEV",
                repository_directory=str(DIRECTORY),
                item_type_in_scope=deploy.ITEM_TYPES,
                token_credential=AzureCliCredential(),
            )
        workspace._refresh_repository_items()
        self.assertEqual(set(workspace.repository_items), set(deploy.ITEM_TYPES))
        workspace.repository_items["SemanticModel"]["Sales"].guid = MODEL_ID
        item = workspace.repository_items["Report"]["Sales"]
        source = (DIRECTORY / "Sales.Report" / "definition.pbir").read_text(encoding="utf-8")
        result = func_process_file(
            workspace, item, SimpleNamespace(name="definition.pbir", contents=source)
        )
        deployed_binding = json.loads(workspace._replace_logical_ids(result))["datasetReference"]
        self.assertNotIn("byPath", deployed_binding)
        self.assertEqual(deployed_binding["byConnection"]["pbiModelDatabaseName"], MODEL_ID)
        self.assertIn("byPath", json.loads(source)["datasetReference"])


if __name__ == "__main__":
    unittest.main()
