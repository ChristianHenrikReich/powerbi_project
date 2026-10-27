# Power BI semantic model and consuming report

A source-controlled Power BI starter following the workspace-folder and
`fabric-cicd` conventions of
[TheEngineersGuideToMicrosoftFabric_Platform_Dev](https://github.com/ChristianHenrikReich/TheEngineersGuideToMicrosoftFabric_Platform_Dev).

The semantic model and report share one reporting workspace in each environment.
CI (`pr-octopus-tst.yml`) octopus-merges open pull requests and deploys the
combined result to tst. A separate CD workflow runs
only after a pull request into main is merged: it ensures dev, tst, and prd
workspaces exist, then deploys only to prd, subject to production approval.

## Structure

```text
.github\
  copilot-instructions.md
  workflows\
    deploy-fabric.yml
    pr-octopus-tst.yml
solution\
  reporting\
    parameter.yml
    Sales.pbip
    Sales.SemanticModel\
      .platform
      definition.pbism
      definition\
        database.tmdl
        model.tmdl
        relationships.tmdl
        tables\
          Product.tmdl
          Sales.tmdl
    Sales.Report\
      .platform
      definition.pbir
      definition\
        version.json
        report.json
        pages\
          pages.json
          <page-id>\
            page.json
            visuals\
      StaticResources\
scripts\
  config.py
  fabric_client.py
  setup_workspaces.py
  deploy.py
  build_report.py
tests\
  test_build_report.py
  test_deployment.py
semantic_model_solution.yml
requirements-deploy.txt
package.json
package-lock.json
```

Repository-wide GitHub Copilot guidance is maintained in
`.github\copilot-instructions.md`.

There are no environment-specific copies of the artifacts. The target environment
selects workspace IDs and parameter replacements at deployment time. Unlike the
reference's lakehouse solution, this starter does not provision unused lakehouses,
warehouses, Key Vault, Bicep resources, or Azure DevOps pipelines.

## Open and develop locally

Use Python 3.12 or newer, Node.js 20 or newer, current Power BI Desktop with
PBIP/TMDL/PBIR support, and Azure CLI for deployment.
Report generation and deployment use Python. Node.js is required for the
Microsoft report-authoring CLI, including validation and preview.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-deploy.txt
npm ci
```

Open `solution\reporting\Sales.pbip` in Power BI Desktop and refresh the model.
The source contains embedded synthetic Power Query data and needs no external
source credentials. PBIP source control contains definitions, not an imported
data cache, so refresh is necessary before the first data preview.

The model has a Product dimension, six sales lines, a single-direction
many-to-one relationship, and three explicit measures. Unfiltered expected
results are **125.00 total sales**, **23 units**, and **5.43 average unit
price** at the measure's two-decimal display precision. Product totals are Notebook 50, Mug 45, and Pen 30. Stationery totals
80 and 20 units; Accessories totals 45 and 3 units. Amounts are unitless demo
values, not actual financial records.

The single-page report contains a category dropdown, separately styled sales
and quantity KPIs, a product-ranking chart, and a product-detail matrix. The
matrix implements the planned detail table with separate dimension/measure
roles, as recommended by the authoring skill. It contains no local semantic
model or copied data: `definition.pbir` refers to `../Sales.SemanticModel`.
Desktop opens that local model for editing; after deployment, the report uses
the target workspace's published model.

```powershell
python -m unittest discover -s tests -v
npm run validate:report
```

Rendered-output checks are separate from schema checks: open/refresh in Desktop,
exercise Category and Product selections, and inspect every visual. Local
automated preview uses the installed report CLI:

```powershell
npx powerbi-report-author preview .\solution\reporting\Sales.Report --host desktop --status
```

For a Microsoft Store installation, set the executable path in the current
PowerShell session before running preview. Resolve it from the package manifest
instead of hardcoding the versioned WindowsApps folder:

```powershell
$package = Get-AppxPackage -Name Microsoft.MicrosoftPowerBIDesktop
if (-not $package) { throw "Power BI Desktop Store package not found for the current user." }
$manifest = Get-AppxPackageManifest -Package $package
$application = @($manifest.Package.Applications.Application) |
    Where-Object { $_.Executable -match '(?i)(^|\\)PBIDesktop\.exe$' } |
    Select-Object -First 1
if (-not $application) { throw "Power BI Desktop executable not found in the package manifest." }
$env:PBI_DESKTOP_PATH = Join-Path $package.InstallLocation $application.Executable
npx powerbi-report-author preview .\solution\reporting\Sales.Report --host desktop --status
```

If status reports no running instance (`HOST_UNAVAILABLE`), open the project:
`npx powerbi-report-author preview .\solution\reporting\Sales.Report --host desktop`.
If status reports an existing instance with unsaved changes, save or resolve
those changes manually before opening/reloading through the CLI.

The optional Python generator regenerates the sample page's six named visuals
and its FHD canvas, using only the Python standard library:

```powershell
python -m scripts.build_report
```

`npm run build:report` remains a convenience alias for the same Python command;
activate the project virtual environment first. The generator is not part of CI:
intentional Desktop edits should be committed directly, not overwritten on every
build. The report shell was generated by the supported report CLI; the TMDL model
was built/exported through the modeling MCP.

## Configure environments

Use dedicated workspaces such as:

| Environment | Workspace | GitHub Environment |
|---|---|---|
| dev | sales-reporting-dev | fabric-dev |
| tst | sales-reporting-tst | fabric-tst |
| prd | sales-reporting-prd | fabric-prd |

Set existing workspace IDs in `semantic_model_solution.yml`, or supply
environment variables such as `REPORTING_DEV_WORKSPACE_ID`. A configured ID
takes precedence over workspace-name discovery; existing names need not match
the suggested naming scheme.

For workspace creation, supply an existing Fabric capacity ID through the
`reporting_capacity` alias, per-environment `capacity` entries, or variables such
as `REPORTING_DEV_CAPACITY_ID`. Aliases can reference other aliases; cycles fail.
Capacity infrastructure itself is not created by this starter.

Empty IDs are deliberate configuration requirements, not working placeholder
GUIDs. Setup resolves an accessible workspace by its exact generated name or
creates it when a capacity is supplied. Duplicate names, invalid GUIDs, missing
capacity, and permission errors fail explicitly. Setup never reassigns the
capacity of an existing workspace.

```powershell
az login
python -m scripts.setup_workspaces --environment dev --dry-run
python -m scripts.setup_workspaces --environment dev
python -m scripts.deploy --workspace reporting --environment dev --refresh
```

For explicitly authorized provisioning of all three environments, use
`python -m scripts.setup_workspaces --environment all` (or add `--dry-run` to
inspect without writes). This reuses existing workspaces and creates only missing
ones; it does not publish or refresh items. The local deployment CLI still
supports selecting dev/tst/prd, but GitHub Actions publishes only to prd.

`--dry-run` reads workspace APIs but makes no changes. Without `--output`, setup
persists the resolved workspace IDs in the input config. In CI, it writes to
`.deploy\resolved-solution.yml` and deploy consumes that file in the same job;
the workflow does not push generated configuration commits.

Deployment publishes SemanticModel before the dependent Report using
fabric-cicd's dependency handling. The library converts the report's local
reference to a service connection for the model published to that environment.
The script then reads back both items and checks the report's actual `datasetId`.
`--refresh` starts a full transactional enhanced refresh and waits up to 30
minutes, failing on refresh errors or timeout. CI enables it so the sample has
data after deployment. Enhanced refresh requires a supported Fabric/Premium
capacity. Refresh failures do not trigger another submission automatically.

Refresh polling uses the accepted operation ID on `api.powerbi.com`, rather than
requiring the service's `Location` URL to exactly match the submission URL.
This supports regional polling locations without sending credentials to arbitrary
hosts. A polling error after HTTP 202 does not imply the refresh failed; inspect
the model's refresh history before submitting another refresh.

Unrelated workspace items are retained. The local-only
`--unpublish-orphans` option is **destructive**: it can remove any SemanticModel
or Report absent from the source folder. Use it only with explicit approval in
a workspace exclusively owned by this repository; CI never enables it.

## GitHub Actions one-time setup

1. Push these files to a GitHub repository with `main` as the deployment branch.
   Protect `main`: require pull requests and a successful tst deployment check, and an
   up-to-date branch (or equivalent merge controls) before merging.
2. Create the GitHub Environment `fabric-prd`. Configure required reviewers and
   restrict deployment branches to `main`. Without required reviewers, production
   runs will not wait for approval. These protections are GitHub settings, not
   something workflow YAML creates. `fabric-dev` and `fabric-tst` are not used
   by this production-only workflow.
3. Configure an Entra application/service principal and workload identity
   federation for the production job. The OIDC subject is
   `repo:<owner>/<repository>:environment:fabric-prd`, with audience
   `api://AzureADTokenExchange`.
4. In `fabric-prd`, add secrets `AZURE_CLIENT_ID` and
   `AZURE_TENANT_ID`. No client secret or Azure subscription is required.
5. In `fabric-prd`, optionally override configured workspace IDs with
   `REPORTING_DEV_WORKSPACE_ID`, `REPORTING_TST_WORKSPACE_ID`, and
   `REPORTING_PRD_WORKSPACE_ID`. The existing `REPORTING_WORKSPACE_ID` variable
   remains a fallback for prd only; it is never reused as the dev/tst ID.
   `REPORTING_CAPACITY_ID` supplies a shared capacity fallback, or use distinct
   `REPORTING_DEV_CAPACITY_ID`, `REPORTING_TST_CAPACITY_ID`, and
   `REPORTING_PRD_CAPACITY_ID`. Nonempty variables override the solution config;
   blank variables leave its values intact. These are GitHub configuration
   variables, not secrets.
6. Enable the tenant settings allowing the identity/security group to call
   Fabric and Power BI APIs. This workflow uses the production identity for all
   workspace provisioning: it needs access to resolve existing dev/tst/prd
   workspaces and workspace-creation/capacity assignment permissions for missing
   ones. Grant Contributor or higher on prd for model/report deployment. It does
   not publish items to dev or tst.

### CI: pull request integration checks

`.github\workflows\pr-octopus-tst.yml` (**Octopus-merge open PRs and deploy to
TST**) follows the reference platform. When a PR is opened, reopened, updated, or
closed, it octopus-merges all open non-draft PRs into main, runs all validation
(unit tests and PBIR schema validation) on the combined tree, then ensures the tst workspace exists and deploys and refreshes the combined
result in tst only. A merge conflict between open PRs fails the run. With no open
PRs, main is deployed to tst as-is. This workflow needs Azure OIDC credentials
that accept the `pull_request` subject, and variables `REPORTING_TST_WORKSPACE_ID`
or `REPORTING_TST_CAPACITY_ID` (or `REPORTING_CAPACITY_ID`).

### CD: merged pull requests only

`.github\workflows\deploy-fabric.yml` (**CD - Deploy merged changes to Fabric**)
listens for closed PRs targeting main, but its jobs run only when
`github.event.pull_request.merged == true`. Unmerged PR closures skip all CD
jobs. Direct pushes and manual dispatch do not trigger deployment. CD contains
no validation; all validation lives in CI.

The workflow uses `pull_request_target` so post-merge deployment can use the
repository's protected production credentials, including for a merged fork PR.
It never checks out an unmerged PR head: it explicitly checks out the
event's `merge_commit_sha`, including for squash/rebase merges. The job waits
for the configured `fabric-prd` approval, then resolves/creates all three
workspaces and deploys and refreshes only prd. Any workspace setup failure stops
the job before publication. Existing dev/tst items are left unchanged.

To retry a failed deployment, use GitHub Actions' **Re-run failed jobs** on the
original merged-PR run; the merged revision remains pinned. This is not a Fabric
Deployment Pipeline or a dev-to-prd promotion chain. Production/provisioning jobs
are serialized and active deployments are not cancelled by newer runs. Unlike
the reference platform's PR-to-TST deployment, this project makes no Fabric
changes while a PR is open.

## Replace the sample with real data

Keep the `.SemanticModel` and `.Report` items together. Retain `.platform` logical
IDs for existing items; changing them can change deployment identity. Put
additional reports in sibling `.Report` directories and bind them to a co-located
semantic model.

Replace embedded M partitions with the real source and introduce shared M
parameters for server/database/warehouse locations. Add a date dimension if dates
are introduced. Parameter replacements belong in `solution\reporting\parameter.yml`
with environment keys **DEV**, **TST**, and **PRD**, for example:

```yaml
find_replace:
  - find_value: "sql-dev.example.invalid"
    replace_value:
      DEV: "sql-dev.example.invalid"
      TST: "sql-tst.example.invalid"
      PRD: "sql-prd.example.invalid"
    item_type: "SemanticModel"
```

Use existing Fabric cloud/gateway connections for real sources, parameterize
their binding per the pinned fabric-cicd documentation, and configure credentials
in the service. Secrets do not belong in TMDL, M, YAML, or report definitions.
Changing a server string is not sufficient to configure authentication or a
gateway. Validate real-source refresh and report data before promotion.

This scaffold does not configure schedules, app publishing, permissions/RLS
membership, gateway infrastructure, or production business data.
