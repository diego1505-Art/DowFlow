param(
    [Parameter(Mandatory = $true)]
    [string]$Repository,
    [Parameter(Mandatory = $true)]
    [string]$Branch,
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"
$project = (Resolve-Path -LiteralPath $ProjectRoot).Path
$markerPath = Join-Path $project ".dowflow-commit"
$preservedNames = @(
    ".venv",
    "downloads",
    "logs",
    "build-work",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".git",
    "config.json",
    "dowflow.db",
    "dowflow.db-wal",
    "dowflow.db-shm",
    ".dowflow-commit"
)

function Get-RepositoryParts {
    param([string]$Url)
    $clean = $Url.TrimEnd('/') -replace '\.git$', ''
    $uri = [Uri]$clean
    $segments = @($uri.AbsolutePath.Trim('/').Split('/')) | Where-Object { $_ }
    if ($segments.Count -ne 2) {
        throw "Unsupported GitHub repository URL: $Url"
    }
    return @{ Owner = $segments[0]; Name = $segments[1] }
}

function Get-RelativePath {
    param([string]$Base, [string]$Path)
    return $Path.Substring($Base.Length).TrimStart('\', '/') -replace '\\', '/'
}

function Test-PreservedPath {
    param([string]$RelativePath)
    $parts = $RelativePath.Split('/')
    return $preservedNames -contains $parts[0]
}

function Get-FileMap {
    param([string]$Root)
    $map = @{}
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        return $map
    }
    foreach ($file in Get-ChildItem -LiteralPath $Root -Recurse -File -Force) {
        $relative = Get-RelativePath $Root $file.FullName
        if (Test-PreservedPath $relative) { continue }
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        $map[$relative] = $hash
    }
    return $map
}

function Test-SameProjectFiles {
    param([string]$CurrentRoot, [string]$ArchiveRoot)
    $current = Get-FileMap $CurrentRoot
    $archive = Get-FileMap $ArchiveRoot
    if ($current.Count -ne $archive.Count) { return $false }
    foreach ($path in $archive.Keys) {
        if (-not $current.ContainsKey($path) -or $current[$path] -ne $archive[$path]) {
            return $false
        }
    }
    return $true
}

function Copy-ProjectFiles {
    param([string]$SourceRoot, [string]$DestinationRoot)
    $sourceFiles = @{}
    foreach ($file in Get-ChildItem -LiteralPath $SourceRoot -Recurse -File -Force) {
        $relative = Get-RelativePath $SourceRoot $file.FullName
        if (Test-PreservedPath $relative) { continue }
        $sourceFiles[$relative] = $file.FullName
    }

    foreach ($file in Get-ChildItem -LiteralPath $DestinationRoot -Recurse -File -Force) {
        $relative = Get-RelativePath $DestinationRoot $file.FullName
        if (Test-PreservedPath $relative) { continue }
        if (-not $sourceFiles.ContainsKey($relative)) {
            Remove-Item -LiteralPath $file.FullName -Force
        }
    }

    foreach ($relative in $sourceFiles.Keys) {
        $destination = Join-Path $DestinationRoot ($relative -replace '/', '\')
        $parent = Split-Path -Parent $destination
        if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
        Copy-Item -LiteralPath $sourceFiles[$relative] -Destination $destination -Force
    }
}

$parts = Get-RepositoryParts $Repository
$apiHeaders = @{ "User-Agent" = "DowFlow-ZIP-Updater"; "Accept" = "application/vnd.github+json" }
$apiUrl = "https://api.github.com/repos/$($parts.Owner)/$($parts.Name)/commits/$Branch"
$latest = Invoke-RestMethod -Uri $apiUrl -Headers $apiHeaders -Method Get
$latestCommit = [string]$latest.sha
if ([string]::IsNullOrWhiteSpace($latestCommit)) {
    throw "GitHub did not return the latest commit for $Branch."
}
$shortCommit = $latestCommit.Substring(0, [Math]::Min(7, $latestCommit.Length))
$subject = [string]$latest.commit.message
$subject = ($subject -split "`r?`n")[0]

$localMarker = ""
if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
    $localMarker = (Get-Content -LiteralPath $markerPath -Raw).Trim()
}

$temporary = Join-Path ([IO.Path]::GetTempPath()) ("dowflow-zip-update-" + [Guid]::NewGuid().ToString("N"))
$archivePath = Join-Path $temporary "latest.zip"
$extractPath = Join-Path $temporary "extracted"
try {
    $needsComparison = [string]::IsNullOrWhiteSpace($localMarker)
    if (-not $needsComparison -and $localMarker -eq $latestCommit) {
        Write-Host "[OK] ZIP is up to date ($shortCommit)."
        exit 0
    }

    # A fresh GitHub ZIP has no commit metadata. Download the archive once so
    # its actual project files can be compared before writing the marker.
    New-Item -ItemType Directory -Force -Path $temporary, $extractPath | Out-Null
    $archiveUrl = "https://codeload.github.com/$($parts.Owner)/$($parts.Name)/zip/refs/heads/$Branch"
    Invoke-WebRequest -Uri $archiveUrl -Headers @{ "User-Agent" = "DowFlow-ZIP-Updater" } -OutFile $archivePath
    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractPath -Force
    $archiveRoot = Get-ChildItem -LiteralPath $extractPath -Directory | Select-Object -First 1
    if ($null -eq $archiveRoot) { throw "The GitHub ZIP did not contain a project folder." }

    if ([string]::IsNullOrWhiteSpace($localMarker) -and (Test-SameProjectFiles $project $archiveRoot.FullName)) {
        Set-Content -LiteralPath $markerPath -Value $latestCommit -Encoding ASCII
        Write-Host "[OK] ZIP project is already current ($shortCommit)."
        exit 0
    }

    Write-Host ""
    Write-Host "A new DowFlow ZIP update is available:"
    Write-Host "Commit: $shortCommit"
    Write-Host "Changes: $subject"
    $answer = Read-Host "Would you like to download and install this update? [Y/N]"
    if ($answer -notmatch '^[Yy]') {
        Write-Host "Project update skipped. Local files are preserved."
        exit 0
    }

    Copy-ProjectFiles $archiveRoot.FullName $project
    Set-Content -LiteralPath $markerPath -Value $latestCommit -Encoding ASCII
    Write-Host "[OK] Project ZIP update installed."
    exit 10
}
finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
    }
}
exit 0
