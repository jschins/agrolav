[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$Version = "",

    [Parameter(Mandatory = $false)]
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ArtifactsRoot = Join-Path $ProjectRoot "artifacts"

$Projects = @(
    "client",
    "hub"
)

# Directories/files that should NOT be shipped.
$ExcludeDirectories = @(
    ".git",
    ".github",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "node_modules"
)

$ExcludeFiles = @(
    "*.pyc",
    "*.pyo",
    ".DS_Store"
)

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

function Write-Step {
    param([string]$Message)

    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Copy-Project {
    param(
        [string]$ProjectName
    )

    $Source = Join-Path $ProjectRoot $ProjectName
    $Destination = Join-Path $ArtifactsRoot $ProjectName

    if (-not (Test-Path $Source)) {
        throw "Project folder does not exist: $Source"
    }

    Write-Step "Copying $ProjectName"

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    # robocopy is used because it handles recursive copies and exclusions
    # much more reliably than Copy-Item.
    $RoboArgs = @(
        $Source
        $Destination
        "/E"
        "/R:2"
        "/W:1"
        "/NFL"
        "/NDL"
        "/NP"
    )

    foreach ($Directory in $ExcludeDirectories) {
        $RoboArgs += "/XD"
        $RoboArgs += (Join-Path $Source $Directory)
    }

    foreach ($File in $ExcludeFiles) {
        $RoboArgs += "/XF"
        $RoboArgs += $File
    }

    & robocopy @RoboArgs

    # Robocopy returns codes 0-7 for success/non-fatal differences.
    if ($LASTEXITCODE -gt 7) {
        throw "Failed to copy $ProjectName. Robocopy exit code: $LASTEXITCODE"
    }
}

# ------------------------------------------------------------
# Determine version
# ------------------------------------------------------------

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = Get-Date -Format "yyyy.MM.dd-HHmmss"
}

$ReleaseDirectory = Join-Path $ArtifactsRoot $Version

# ------------------------------------------------------------
# Prepare artifacts
# ------------------------------------------------------------

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " FastAPI Release Bootstrapper" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green

Write-Host ""
Write-Host "Project root : $ProjectRoot"
Write-Host "Version      : $Version"
Write-Host "Output       : $ReleaseDirectory"

if (Test-Path $ReleaseDirectory) {
    if ($Clean) {
        Write-Step "Removing existing release: $Version"
        Remove-Item -Recurse -Force $ReleaseDirectory
    }
    else {
        throw "Release already exists: $ReleaseDirectory`nUse -Clean to overwrite it."
    }
}

New-Item -ItemType Directory -Force -Path $ReleaseDirectory | Out-Null

# ------------------------------------------------------------
# Copy projects
# ------------------------------------------------------------

foreach ($Project in $Projects) {
    $ArtifactsRootBackup = $ArtifactsRoot

    # Temporarily point the copy destination at the versioned release.
    $ArtifactsRoot = $ReleaseDirectory

    try {
        Copy-Project -ProjectName $Project
    }
    finally {
        $ArtifactsRoot = $ArtifactsRootBackup
    }
}

# ------------------------------------------------------------
# Create release metadata
# ------------------------------------------------------------

Write-Step "Creating release metadata"

$Metadata = @{
    version      = $Version
    createdAtUtc = [DateTime]::UtcNow.ToString("o")
    projects     = $Projects
}

$Metadata |
    ConvertTo-Json -Depth 5 |
    Set-Content -Path (Join-Path $ReleaseDirectory "release.json") -Encoding UTF8

# ------------------------------------------------------------
# Create/update latest
# ------------------------------------------------------------

$LatestDirectory = Join-Path $ArtifactsRoot "latest"

if (Test-Path $LatestDirectory) {
    Remove-Item -Recurse -Force $LatestDirectory
}

Copy-Item `
    -Path $ReleaseDirectory `
    -Destination $LatestDirectory `
    -Recurse `
    -Force

# ------------------------------------------------------------
# Done
# ------------------------------------------------------------

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " Release created successfully!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green

Write-Host ""
Write-Host "Release:" -ForegroundColor Yellow
Write-Host "  $ReleaseDirectory"

Write-Host ""
Write-Host "Latest:" -ForegroundColor Yellow
Write-Host "  $LatestDirectory"

Write-Host ""
Write-Host "Contents:" -ForegroundColor Yellow
Get-ChildItem $ReleaseDirectory |
    Select-Object Name, Mode |
    Format-Table -AutoSize
