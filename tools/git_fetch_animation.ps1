param(
    [Parameter(Mandatory = $true)]
    [string]$Repository,
    [Parameter(Mandatory = $true)]
    [string]$Branch,
    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)

$colors = @("Cyan", "Magenta", "Yellow", "Green", "Blue")
$colorIndex = 0
$nextColorChange = [DateTime]::UtcNow.AddSeconds(10)
$trackWidth = 32
$frame = 0
$exitCode = 1
$fetchJob = $null

try {
    $fetchJob = Start-Job -ArgumentList $Repository, $Branch, $ProjectRoot -ScriptBlock {
        param($Remote, $RemoteBranch, $WorkingDirectory)
        Set-Location -LiteralPath $WorkingDirectory
        & git fetch $Remote $RemoteBranch --quiet
        [int]$LASTEXITCODE
    }

    while ($fetchJob.State -in @("NotStarted", "Running")) {
        if ([DateTime]::UtcNow -ge $nextColorChange) {
            $colorIndex = ($colorIndex + 1) % $colors.Count
            $nextColorChange = [DateTime]::UtcNow.AddSeconds(10)
        }

        $position = $frame % $trackWidth
        $bar = ("=" * $position) + ">" + ("=" * ($trackWidth - $position))
        $line = "[$bar] Downloading project update..."
        Write-Host ("`r" + $line.PadRight($trackWidth + 40)) -ForegroundColor $colors[$colorIndex] -NoNewline
        $frame++
        Start-Sleep -Milliseconds 90
        $fetchJob = Get-Job -Id $fetchJob.Id
    }

    $fetchResult = @(Receive-Job -Job $fetchJob -Wait)
    if ($fetchJob.State -eq "Completed" -and $fetchResult.Count -gt 0) {
        $exitCode = [int]$fetchResult[-1]
    }
}
catch {
    Write-Host "`r[ERROR] GitHub update download failed." -ForegroundColor Red
    Write-Error $_
    $exitCode = 1
}
finally {
    if ($null -ne $fetchJob) {
        if ($fetchJob.State -in @("NotStarted", "Running")) {
            Stop-Job -Job $fetchJob -ErrorAction SilentlyContinue
        }
        Remove-Job -Job $fetchJob -Force -ErrorAction SilentlyContinue
    }
}

if ($exitCode -eq 0) {
    Write-Host ("`r[OK] Project update downloaded.".PadRight($trackWidth + 40)) -ForegroundColor Green
} else {
    Write-Host ("`r[ERROR] GitHub update download failed.".PadRight($trackWidth + 40)) -ForegroundColor Red
}

exit $exitCode