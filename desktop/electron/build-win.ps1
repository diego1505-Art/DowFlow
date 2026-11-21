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
$linerRoot = (Resolve-Path (Join-Path $PSScriptRoot "../liner")).Path
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$backendExe = Join-Path $repoRoot "build/out/DowFlow/DowFlow.exe"

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

    Push-Location $linerRoot
    try {
        Invoke-Checked "pnpm" @("install", "--frozen-lockfile")
        Invoke-Checked "pnpm" @("check")
        Invoke-Checked "pnpm" @("native:build")
        Invoke-Checked "pnpm" @("exec", "electron-builder", "--win", "--dir", "--x64")
    }
    finally {
        Pop-Location
    }

    $linerExe = Join-Path $linerRoot "release/win-unpacked/dowflow-music.exe"
    if (-not (Test-Path -LiteralPath $linerExe -PathType Leaf)) {
        throw "Electron Builder did not produce the packaged DowFlow Music app at $linerExe."
    }

    Push-Location $electronRoot
    try {
        Invoke-Checked "pnpm" @("exec", "electron-builder", "--win", "nsis", "--x64")
    }
    finally {
        Pop-Location
    }

    $bundledLinerExe = Join-Path $electronRoot "release/win-unpacked/resources/liner/dowflow-music.exe"
    if (-not (Test-Path -LiteralPath $bundledLinerExe -PathType Leaf)) {
        throw "The DowFlow Windows package does not contain the bundled DowFlow Music app at $bundledLinerExe."
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
