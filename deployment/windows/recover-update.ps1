param(
    [string]$InstallRoot = "C:\Monitoring\WiiconChatBot_5",
    [string]$PackagePath = ""
)

$ErrorActionPreference = "Stop"
$TaskName = "WiiconChatBot5"
$ServicePort = 7786
$StageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("WiiconChatBot5-recovery-" + [System.Guid]::NewGuid().ToString("N"))
$Applied = $false

function Stop-WiiconProcesses {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    $patterns = @("run-bot.cmd", "run_windows_supervisor.py", "run_wiic_bwiki.py", "wiicon5.cli.serve")
    Get-CimInstance Win32_Process | Where-Object {
        $process = $_
        if ($process.ProcessId -eq $PID -or -not $process.CommandLine -or -not $process.CommandLine.Contains($InstallRoot)) {
            return $false
        }
        foreach ($pattern in $patterns) {
            if ($process.CommandLine.Contains($pattern)) { return $true }
        }
        return $false
    } | Sort-Object ProcessId -Descending | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
}

function Start-WiiconTask {
    Start-ScheduledTask -TaskName $TaskName
}

function Wait-WiiconHealth([int]$TimeoutSeconds = 90) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:$ServicePort/health" -TimeoutSec 2
            if ($response.ok) { return $true }
        } catch {}
        Start-Sleep -Seconds 1
    }
    return $false
}

try {
    if (-not $PackagePath) {
        $PackagePath = Get-ChildItem -Path (Join-Path $InstallRoot "updates\failed"), (Join-Path $InstallRoot "updates\inbox") -Filter "wiicon5-update-*.zip" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $PackagePath -or -not (Test-Path $PackagePath)) {
        throw "Update package was not found. Pass -PackagePath explicitly."
    }
    $PackagePath = [System.IO.Path]::GetFullPath($PackagePath)
    Write-Host "Recovery package: $PackagePath"
    New-Item -ItemType Directory -Path $StageRoot -Force | Out-Null
    Expand-Archive -LiteralPath $PackagePath -DestinationPath $StageRoot -Force
    $Helper = Join-Path $StageRoot "payload\app\scripts\apply_stopped_update.py"
    if (-not (Test-Path $Helper)) {
        throw "The package does not contain scripts\apply_stopped_update.py. Use update alpha.95 or newer."
    }

    Stop-WiiconProcesses
    & (Join-Path $InstallRoot "runtime\python.exe") $Helper --install-root $InstallRoot --package $PackagePath
    if ($LASTEXITCODE -ne 0) { throw "Update helper failed with exit code $LASTEXITCODE." }
    $Applied = $true
    Start-WiiconTask
    if (-not (Wait-WiiconHealth)) {
        throw "Updated service did not pass health-check within 90 seconds."
    }

    $AppliedRoot = Join-Path $InstallRoot "updates\applied"
    New-Item -ItemType Directory -Path $AppliedRoot -Force | Out-Null
    $TargetPackage = Join-Path $AppliedRoot ([System.IO.Path]::GetFileName($PackagePath))
    if ([System.IO.Path]::GetFullPath($PackagePath) -ine [System.IO.Path]::GetFullPath($TargetPackage)) {
        Move-Item -LiteralPath $PackagePath -Destination $TargetPackage -Force
    }
    Remove-Item (Join-Path $InstallRoot "updates\apply-request.json") -Force -ErrorAction SilentlyContinue
    Write-Host "Recovery update completed successfully."
    Get-Content (Join-Path $InstallRoot "app\current\VERSION")
} catch {
    Write-Error $_
    if ($Applied) {
        Stop-WiiconProcesses
        $Helper = Join-Path $StageRoot "payload\app\scripts\apply_stopped_update.py"
        & (Join-Path $InstallRoot "runtime\python.exe") $Helper --install-root $InstallRoot --rollback
        Start-WiiconTask
        Write-Warning "The previous application version was restored."
    } else {
        Start-WiiconTask
    }
    exit 1
} finally {
    Remove-Item $StageRoot -Recurse -Force -ErrorAction SilentlyContinue
}
