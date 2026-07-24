param(
    [switch]$SkipHistoryScan
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$reportDirectory = Join-Path $projectRoot "outputs\acceptance"
$reportPath = Join-Path $reportDirectory "acceptance-v06.json"
$results = [System.Collections.Generic.List[object]]::new()

function Invoke-AcceptanceStep {
    param(
        [string]$Name,
        [string]$Executable,
        [string[]]$Arguments,
        [string]$WorkingDirectory
    )

    $started = Get-Date
    Push-Location $WorkingDirectory
    try {
        & $Executable @Arguments
        $exitCode = $LASTEXITCODE
        if ($null -eq $exitCode) {
            $exitCode = 0
        }
    }
    catch {
        Write-Error -ErrorAction Continue "$Name failed: $($_.Exception.Message)"
        $exitCode = 1
    }
    finally {
        Pop-Location
    }
    $results.Add([pscustomobject]@{
        name = $Name
        status = $(if ($exitCode -eq 0) { "passed" } else { "failed" })
        exitCode = $exitCode
        elapsedMs = [int]((Get-Date) - $started).TotalMilliseconds
    })
}

Invoke-AcceptanceStep `
    -Name "python-tests" `
    -Executable "python" `
    -Arguments @("-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v") `
    -WorkingDirectory (Join-Path $projectRoot "backend")

Invoke-AcceptanceStep `
    -Name "typescript" `
    -Executable "npx.cmd" `
    -Arguments @("tsc", "--noEmit") `
    -WorkingDirectory $projectRoot

Invoke-AcceptanceStep `
    -Name "eslint" `
    -Executable "npx.cmd" `
    -Arguments @("eslint", ".", "--ignore-pattern", "dist", "--ignore-pattern", ".next") `
    -WorkingDirectory $projectRoot

Invoke-AcceptanceStep `
    -Name "production-build" `
    -Executable "npx.cmd" `
    -Arguments @("vite", "build") `
    -WorkingDirectory $projectRoot

Invoke-AcceptanceStep `
    -Name "rendered-api-tests" `
    -Executable "node" `
    -Arguments @("--test", "tests\rendered-html.test.mjs") `
    -WorkingDirectory $projectRoot

Invoke-AcceptanceStep `
    -Name "tracked-tree-secret-scan" `
    -Executable "node" `
    -Arguments @("scripts\scan-secrets.mjs") `
    -WorkingDirectory $projectRoot

Invoke-AcceptanceStep `
    -Name "client-artifact-secret-scan" `
    -Executable "node" `
    -Arguments @("scripts\scan-secrets.mjs", "--artifact", "dist\client") `
    -WorkingDirectory $projectRoot

if (-not $SkipHistoryScan) {
    Invoke-AcceptanceStep `
        -Name "git-history-secret-scan" `
        -Executable "node" `
        -Arguments @("scripts\scan-secrets.mjs", "--history") `
        -WorkingDirectory $projectRoot
}
else {
    $results.Add([pscustomobject]@{
        name = "git-history-secret-scan"
        status = "skipped"
        exitCode = 0
        elapsedMs = 0
    })
}

New-Item -ItemType Directory -Force -Path $reportDirectory | Out-Null
$failed = @($results | Where-Object { $_.status -eq "failed" })
$report = [pscustomobject]@{
    schemaVersion = "1.0"
    applicationVersion = "0.6.0"
    generatedAtUtc = (Get-Date).ToUniversalTime().ToString("o")
    status = $(if ($failed.Count -eq 0) { "passed" } else { "failed" })
    steps = $results
}
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding UTF8
Write-Host "Acceptance report: $reportPath"

if ($failed.Count -gt 0) {
    exit 1
}
