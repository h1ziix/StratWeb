[CmdletBinding()]
param(
    [ValidateSet("3.11", "3.12", "3.13", "3.14")]
    [string]$PythonVersion = "3.13",
    [switch]$AllowDirty,
    [switch]$SkipTests,
    [switch]$SkipContainerCheck
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory)]
        [string]$Label,
        [Parameter(Mandatory)]
        [string]$Executable,
        [Parameter(Mandatory)]
        [string[]]$Arguments
    )

    Write-Host "==> $Label"
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

Push-Location -LiteralPath $projectRoot
try {
    $uvCommand = Get-Command uv -ErrorAction Stop
    $gitCommand = Get-Command git -ErrorAction Stop

    if (-not $AllowDirty) {
        $status = & $gitCommand.Source status --porcelain
        if ($LASTEXITCODE -ne 0) {
            throw "Could not inspect the Git worktree."
        }
        if ($status) {
            throw "Release check requires a clean worktree. Use -AllowDirty only during development."
        }
    }

    Invoke-Checked "Lockfile validation" $uvCommand.Source @("lock", "--check")
    Invoke-Checked "Frozen environment sync" $uvCommand.Source @(
        "sync", "--frozen", "--extra", "dev", "--python", $PythonVersion
    )

    $runningOnWindows = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT
    $pythonPath = if ($runningOnWindows) {
        Join-Path $projectRoot ".venv\Scripts\python.exe"
    } else {
        Join-Path $projectRoot ".venv/bin/python"
    }
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "Frozen environment did not create its Python executable: $pythonPath"
    }

    Invoke-Checked "Dependency consistency" $pythonPath @("-m", "pip", "check")
    Invoke-Checked "Formatting" $pythonPath @(
        "-m", "ruff", "format", "--check", "src", "tests", "scripts"
    )
    Invoke-Checked "Lint" $pythonPath @("-m", "ruff", "check", "src", "tests", "scripts")
    Invoke-Checked "Strict typing" $pythonPath @("-m", "mypy", "src")
    if (-not $SkipTests) {
        Invoke-Checked "Non-integration tests" $pythonPath @(
            "-m", "pytest", "-m", "not integration"
        )
    }
    Invoke-Checked "Application import" $pythonPath @(
        "-c",
        "import importlib.metadata as metadata; import stratweb; from stratweb.main import create_app; assert metadata.version('stratweb') == stratweb.__version__; assert create_app().title == 'StratWeb'"
    )
    $packageVersion = (& $pythonPath -c "import stratweb; print(stratweb.__version__)").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $packageVersion) {
        throw "Could not resolve the installed StratWeb version."
    }
    Invoke-Checked "Golden Corpus contract" $pythonPath @(
        "-m", "stratweb.cli", "corpus", "validate",
        "--manifest", "corpus/golden-corpus-v1.json"
    )

    $artifactDirectory = Join-Path $projectRoot ".runtime\release-check\dist"
    New-Item -ItemType Directory -Path $artifactDirectory -Force | Out-Null
    Invoke-Checked "Wheel build" $uvCommand.Source @(
        "build", "--wheel", "--out-dir", $artifactDirectory
    )
    $wheel = Get-ChildItem -LiteralPath $artifactDirectory -Filter "stratweb-$packageVersion-*.whl" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $wheel) {
        throw "The expected StratWeb $packageVersion wheel was not produced."
    }

    if (-not $SkipContainerCheck) {
        $dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
        if ($null -eq $dockerCommand) {
            throw "Docker is required unless -SkipContainerCheck is supplied."
        }
        Invoke-Checked "Compose validation" $dockerCommand.Source @(
            "compose", "config", "--quiet"
        )
    }

    Write-Host "StratWeb release checks passed."
    Write-Host "Wheel: $($wheel.FullName)"
} finally {
    Pop-Location
}
