[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [switch]$Reload,
    [string]$DatabasePath,
    [string]$MapOverviewDir
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$appDirectory = Join-Path $projectRoot "src"

$localAppData = $env:LOCALAPPDATA
if (-not $localAppData) {
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
}
if (-not $localAppData) {
    throw "Could not resolve LOCALAPPDATA for portable runtime storage."
}
$runtimeRoot = Join-Path $localAppData "StratWeb"

$resolvedDatabasePath = if ($DatabasePath) {
    $DatabasePath
} elseif ($env:STRATWEB_DUCKDB_PATH) {
    $env:STRATWEB_DUCKDB_PATH
} else {
    Join-Path $runtimeRoot "stratweb.duckdb"
}
$resolvedMapOverviewDir = if ($MapOverviewDir) {
    $MapOverviewDir
} elseif ($env:STRATWEB_MAP_OVERVIEW_DIR) {
    $env:STRATWEB_MAP_OVERVIEW_DIR
} else {
    Join-Path $runtimeRoot "map_overviews"
}

foreach ($requiredPath in @($pythonPath, $appDirectory)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required project path does not exist: $requiredPath"
    }
}

$databaseDirectory = Split-Path -Parent $resolvedDatabasePath
foreach ($runtimeDirectory in @($databaseDirectory, $resolvedMapOverviewDir)) {
    if ($runtimeDirectory) {
        New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
    }
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $owner = ($listener | Select-Object -First 1).OwningProcess
    throw "Port $Port is already in use by process $owner. Open http://127.0.0.1:$Port/ui or stop that process first."
}

$env:STRATWEB_DUCKDB_PATH = $resolvedDatabasePath
$env:STRATWEB_MAP_OVERVIEW_DIR = $resolvedMapOverviewDir

$uvicornArguments = @(
    "-m",
    "uvicorn",
    "stratweb.main:app",
    "--app-dir",
    $appDirectory,
    "--host",
    "127.0.0.1",
    "--port",
    "$Port"
)
if ($Reload) {
    $uvicornArguments += "--reload"
}

Set-Location -LiteralPath $projectRoot
Write-Host "StratWeb: http://127.0.0.1:$Port/ui"
Write-Host "Database: $resolvedDatabasePath"
Write-Host "Map assets: $resolvedMapOverviewDir"
Write-Host "Stop the server with Ctrl+C."

& $pythonPath @uvicornArguments
exit $LASTEXITCODE
