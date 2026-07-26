param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [switch]$Reload,
    # Runtime data lives outside OneDrive: sync conflicts can corrupt DuckDB files.
    [string]$DatabasePath = "C:\Users\rausa\StratWeb-data\faceit-spatial.duckdb",
    [string]$MapOverviewDir = "C:\Users\rausa\StratWeb-data\map_overviews"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$databasePath = $DatabasePath
$mapOverviewPath = $MapOverviewDir

foreach ($requiredPath in @($pythonPath, $databasePath, $mapOverviewPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required path does not exist: $requiredPath"
    }
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $owner = ($listener | Select-Object -First 1).OwningProcess
    throw "Port $Port is already in use by process $owner. Open http://127.0.0.1:$Port/ui or stop that process first."
}

$env:STRATWEB_DUCKDB_PATH = $databasePath
$env:STRATWEB_MAP_OVERVIEW_DIR = $mapOverviewPath

$uvicornArguments = @(
    "-m",
    "uvicorn",
    "stratweb.main:app",
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
Write-Host "Database: $databasePath"
Write-Host "Map assets: $mapOverviewPath"
Write-Host "Stop the server with Ctrl+C."

& $pythonPath @uvicornArguments
exit $LASTEXITCODE
