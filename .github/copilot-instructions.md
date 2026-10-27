# Copilot instructions

This is the single source of repository-wide instructions for GitHub Copilot.
Read `README.md` for setup, authentication, and deployment procedures. Keep these
instructions aligned with that document.

## Project architecture

- This repository contains a Power BI semantic model and its consuming report,
  deployed through Python and fabric-cicd.
- Artifacts belong in `solution\<workspace-type>`. The current workspace type is
  `reporting`; its semantic model and reports share one workspace per environment.
- Environments are `dev`, `tst`, and `prd`. Do not create environment-specific
  copies of model or report folders.
- `semantic_model_solution.yml` holds workspace/capacity configuration.
  `scripts\config.py` implements aliases, GUID validation, and environment
  overrides. Reuse it instead of introducing another configuration loader.
- Keep environment-specific source substitutions in
  `solution\reporting\parameter.yml`, using `DEV`, `TST`, and `PRD` keys.

## Model and report authoring

- Use the `semantic-model-authoring` and `powerbi-report-cli` skills when
  available. Follow their applicable authoring and validation workflows.
- Prefer the modeling MCP for model changes, then export the changes into the
  semantic model's `definition` directory. Do not mix edits to a loaded model
  with direct edits to potentially stale TMDL files.
- Preserve TMDL semantic models and enhanced PBIR reports. Use the supported
  report CLI to scaffold new report shells and inspect visual capabilities;
  do not guess schemas, visual roles, or formatting properties.
- Preserve `.platform` logical IDs across deployments and renames. In source
  control, consuming reports use a
  relative `byPath` model reference; fabric-cicd resolves the deployed binding.
  PBIP/PBIR relative references require forward slashes even on Windows.
- Prefer star schemas, single-direction relationships, explicit measures with
  descriptions and format strings, and hidden technical/aggregated columns.
- `npm run build:report` regenerates the sample page and its six named visuals.
  Do not run it over intentional report edits without preserving those edits.
- Report schema validation does not prove correct rendering. For rendered
  changes, also open/refresh the model and inspect affected report pages using
  the skill's preview workflow. State clearly when live or rendered verification
  is unavailable.
- For Store-installed Desktop, use the package-manifest discovery documented in
  `README.md` to set `PBI_DESKTOP_PATH`. Never hardcode a versioned WindowsApps
  executable path or overwrite unsaved Desktop changes.

## Development and validation

- Use PowerShell and Windows-style filesystem paths for this workspace.
- Python dependencies are pinned in `requirements-deploy.txt`; the report CLI is
  pinned in `package.json` and `package-lock.json`. Keep manifests and lockfiles
  consistent when changing dependencies.
- Reuse `scripts\fabric_client.py` for shared REST operations. Surface invalid
  configuration, API failures, and refresh failures explicitly.
- Keep tests independent of real workspace IDs, credentials, and tenant data.
  Use the test fixtures rather than assuming the checked-in solution config has
  empty IDs. Mock cloud writes in automated tests.
- Run the smallest relevant checks after code changes. Standard local commands,
  from the project root with dependencies installed, are:

  ```powershell
  .\.venv\Scripts\python.exe -m unittest discover -s tests -v
  npm run validate:report
  ```

- Documentation-only changes do not require model refresh or deployment.
- Update directly related documentation when behavior or setup changes. Preserve
  unrelated user changes.

## Git commits

- Keep commits small and reviewable, with exactly one logical change per commit.
  Split unrelated changes into separate commits.
- A single logical change may span many files, such as a consistent rename
  throughout the project. Keep those related edits together in one commit.

## Authentication and deployment safety

- Use `AzureCliCredential`: local scripts consume the current Azure CLI login,
  while GitHub Actions establishes that login through OIDC. Do not add client
  secrets to code, model definitions, configuration, logs, or examples.
- Do not deploy, refresh shared models, create workspaces, delete orphan items,
  or accept licenses without user authorization.
- Verify target environment and workspace before cloud writes. Do not replace
  configured IDs, alter tenant settings, or grant permissions to bypass an error.
- Preserve post-deployment checks that both items exist and the report's
  `datasetId` matches the target environment's semantic model.
- HTTP 202 means a refresh was accepted, not completed or failed. Poll by its
  operation ID using the canonical Power BI API. If polling fails, inspect the
  existing operation before resubmitting; do not blindly repeat deployment.
- Keep orphan deletion opt-in. `--unpublish-orphans` is destructive and must not
  be enabled in CI or used in a shared workspace without explicit approval.
- Pull requests validate without cloud credentials. Only `main` deploys: pushes
  target dev, and manual dispatch selects dev/tst/prd. Preserve environment-scoped
  OIDC credentials, per-environment deployment serialization, and the absence of
  automatic configuration commits. Tst/prd approvals are configured in GitHub
  Environment settings, not created by workflow YAML.
- Never commit PBIX files, imported-data caches, user-local settings, credentials,
  or temporary validation screenshots.
