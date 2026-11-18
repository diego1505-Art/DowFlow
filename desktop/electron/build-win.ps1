$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$File,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$File failed with exit code $LASTEXITCODE."
    }
}

$electronRoot = (Resolve-Path $PSScriptRoot).Path
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$backendExe = Join-Path $repoRoot "dist/DowFlow.exe"

Push-Location $repoRoot
try {
    Invoke-Checked "python" @("-m", "pip", "install", "-r", "requirements-build.txt")
    Invoke-Checked "python" @("-m", "pip", "install", "setuptools==42.0.1")

    Push-Location $electronRoot
    try {
        Invoke-Checked "pnpm" @("install", "--frozen-lockfile")
        Invoke-Checked "pnpm" @("check")
    }
    finally {
        Pop-Location
    }

    $env:DOWFLOW_ELECTRON_BUILD = "1"
    try {
        Invoke-Checked "python" @("-m", "build_export", "all", "DowFlow")
    }
    finally {
        Remove-Item Env:DOWFLOW_ELECTRON_BUILD -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path -LiteralPath $backendExe -PathType Leaf)) {
        throw "PyInstaller did not produce the required backend at $backendExe."
    }

    Push-Location $electronRoot
    try {
        Invoke-Checked "pnpm" @("exec", "electron-builder", "--win", "nsis", "--x64")
    }
    finally {
        Pop-Location
    }

    $artifacts = @(Get-ChildItem -Path (Join-Path $electronRoot "release") -Filter "DowFlow-*-x64.exe" -File)
    if ($artifacts.Count -eq 0) {
        throw "Electron Builder completed without creating the expected DowFlow x64 installer."
    }

    Write-Host "Windows installer created: $($artifacts[-1].FullName)"
}
finally {
    Pop-Location
}
