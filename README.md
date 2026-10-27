# Power BI semantic model and consuming report

A source-controlled Power BI starter following the workspace-folder and
`fabric-cicd` conventions of
[TheEngineersGuideToMicrosoftFabric_Platform_Dev](https://github.com/ChristianHenrikReich/TheEngineersGuideToMicrosoftFabric_Platform_Dev).

The semantic model and report share one reporting workspace in each environment.
GitHub Actions validates pull requests, deploys main to dev, and supports manual
deployment of main to tst or prd.

## Structure

```text
.github\
  copilot-instructions.md
  workflows\
    deploy-fabric.yml
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

`--dry-run` reads workspace APIs but makes no changes. Without `--output`, setup
persists the selected workspace ID in the input config. In CI, it writes to
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
2. Create GitHub Environments `fabric-dev`, `fabric-tst`, and `fabric-prd`.
   Configure required reviewers and deployment branch restrictions for tst/prd.
   Required reviewers are a GitHub setting, not something workflow YAML creates.
3. Configure an Entra application/service principal and workload identity
   federation for each environment. The OIDC subject is
   `repo:<owner>/<repository>:environment:fabric-dev` (and equivalent tst/prd
   subjects), with audience `api://AzureADTokenExchange`. Separate deployment
   identities per environment are supported and recommended.
4. In each GitHub Environment, add secrets `AZURE_CLIENT_ID` and
   `AZURE_TENANT_ID`. No client secret or Azure subscription is required.
5. Add environment variable `REPORTING_WORKSPACE_ID` for an existing workspace,
   or `REPORTING_CAPACITY_ID` when setup should resolve/create the generated
   workspace. These are GitHub configuration variables, not secrets.
6. Enable the tenant settings allowing the identity/security group to call
   Fabric and Power BI APIs. Grant it an appropriate workspace role (Contributor
   or higher for item deployment) and the additional workspace-creation/capacity
   assignment permissions if setup will create workspaces.

Pull requests run only credential-free validation. A push to main runs validation
then deploys dev. To promote, manually run **Validate and deploy Power BI**, select
the **main** branch and tst or prd, and approve the environment deployment. Manual
runs on other branches validate but do not deploy. The selected main commit is
deployed directly; this is not a Fabric Deployment Pipeline or an artifact
promotion chain. Deployments to the same environment are serialized.

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
