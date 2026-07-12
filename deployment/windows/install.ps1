$ErrorActionPreference = "Stop"

$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceRoot = $PackageRoot
$InstallRoot = "C:\Monitoring\WiiconChatBot_5"
$LegacyInstallRoot = "C:\ProgramData\WiiconChatBot5"
$TaskName = "WiiconChatBot5"
$ServerName = "ms-1cmonitor"
$ServicePort = 7786
$StagedSourceRoot = $null

trap {
    if ($StagedSourceRoot -and (Test-Path $StagedSourceRoot)) {
        Remove-Item $StagedSourceRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
}

function Copy-NewFilesOnly([string]$Source, [string]$Destination) {
    if (-not (Test-Path $Source)) { return }
    Get-ChildItem -Path $Source -File -Recurse | ForEach-Object {
        $relative = $_.FullName.Substring($Source.Length).TrimStart('\')
        $target = Join-Path $Destination $relative
        $parent = Split-Path -Parent $target
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
        if (-not (Test-Path $target)) {
            Copy-Item $_.FullName $target
        }
    }
}

function Stop-InstalledWiiconProcesses([string]$Root) {
    $patterns = @("run-bot.cmd", "run_windows_supervisor.py", "run_wiic_bwiki.py", "wiicon5.cli.serve")
    Get-CimInstance Win32_Process | Where-Object {
        $process = $_
        if ($process.ProcessId -eq $PID -or -not $process.CommandLine -or -not $process.CommandLine.Contains($Root)) {
            return $false
        }
        foreach ($pattern in $patterns) {
            if ($process.CommandLine.Contains($pattern)) { return $true }
        }
        return $false
    } | Sort-Object ProcessId -Descending | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

$NormalizedPackageRoot = [System.IO.Path]::GetFullPath($PackageRoot).TrimEnd('\')
$NormalizedInstallRoot = [System.IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
if ($NormalizedPackageRoot -ieq $NormalizedInstallRoot) {
    $StagedSourceRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("WiiconChatBot5-install-" + [System.Guid]::NewGuid().ToString("N"))
    Write-Host "Installer is running from the target directory. Staging payload at $StagedSourceRoot"
    New-Item -ItemType Directory -Path $StagedSourceRoot -Force | Out-Null
    foreach ($directory in @("app\current", "runtime", "data_seed")) {
        $sourceDirectory = Join-Path $PackageRoot $directory
        if (Test-Path $sourceDirectory) {
            $targetDirectory = Join-Path $StagedSourceRoot $directory
            New-Item -ItemType Directory -Path (Split-Path -Parent $targetDirectory) -Force | Out-Null
            Copy-Item $sourceDirectory $targetDirectory -Recurse -Force
        }
    }
    foreach ($file in @("run-bot.cmd", "apply-update.cmd", "recover-update.ps1", "server.env", "server.env.example")) {
        $sourceFile = Join-Path $PackageRoot $file
        if (Test-Path $sourceFile) {
            Copy-Item $sourceFile (Join-Path $StagedSourceRoot $file) -Force
        }
    }
    $SourceRoot = $StagedSourceRoot
}

Write-Host "Installing WIICON ChatBot 5 into $InstallRoot"
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask -and $ExistingTask.State -eq "Running") {
    Stop-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 3
}
Stop-InstalledWiiconProcesses $InstallRoot
Start-Sleep -Seconds 2
New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
foreach ($directory in @("app", "runtime", "data", "config", "logs", "updates\inbox", "updates\applied", "updates\failed")) {
    New-Item -ItemType Directory -Path (Join-Path $InstallRoot $directory) -Force | Out-Null
}

if ((Test-Path $LegacyInstallRoot) -and (-not (Test-Path (Join-Path $InstallRoot "config\.env.wiicon5")))) {
    Write-Host "Previous installation found at $LegacyInstallRoot. Migrating configuration and runtime data."
    foreach ($directory in @("config", "data", "logs", "updates")) {
        $legacyPath = Join-Path $LegacyInstallRoot $directory
        if (Test-Path $legacyPath) {
            Get-ChildItem -LiteralPath $legacyPath -Force | ForEach-Object {
                Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $InstallRoot $directory) -Recurse -Force
            }
        }
    }
    $legacyToken = Join-Path $LegacyInstallRoot "ADMIN_TOKEN.txt"
    if (Test-Path $legacyToken) {
        Copy-Item $legacyToken (Join-Path $InstallRoot "ADMIN_TOKEN.txt") -Force
    }
}

if (Test-Path (Join-Path $InstallRoot "app\current")) {
    $backup = Join-Path $InstallRoot "app\preinstall-backup"
    if (Test-Path $backup) { Remove-Item $backup -Recurse -Force }
    Move-Item (Join-Path $InstallRoot "app\current") $backup
}
Copy-Item (Join-Path $SourceRoot "app\current") (Join-Path $InstallRoot "app\current") -Recurse -Force
Copy-Item (Join-Path $SourceRoot "runtime\*") (Join-Path $InstallRoot "runtime") -Recurse -Force
Copy-NewFilesOnly (Join-Path $SourceRoot "data_seed") (Join-Path $InstallRoot "data")

foreach ($file in @("run-bot.cmd", "apply-update.cmd", "recover-update.ps1")) {
    Copy-Item (Join-Path $SourceRoot $file) (Join-Path $InstallRoot $file) -Force
}

$ConfigPath = Join-Path $InstallRoot "config\.env.wiicon5"
$ProvidedConfig = Join-Path $SourceRoot "server.env"
if ((Test-Path $ProvidedConfig) -or (-not (Test-Path $ConfigPath))) {
    $templatePath = if (Test-Path $ProvidedConfig) { $ProvidedConfig } else { Join-Path $SourceRoot "server.env.example" }
    $template = Get-Content $templatePath -Raw -Encoding UTF8
    $tokenBytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($tokenBytes)
    $token = [Convert]::ToBase64String($tokenBytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    if ($template -match "(?m)^WIICON5_ADMIN_TOKEN=\s*$") {
        $template = $template -replace "(?m)^WIICON5_ADMIN_TOKEN=\s*$", "WIICON5_ADMIN_TOKEN=$token"
    } elseif ($template -match "(?m)^WIICON5_ADMIN_TOKEN=(.+)$") {
        $token = $Matches[1].Trim()
    } else {
        $template += "`r`nWIICON5_ADMIN_TOKEN=$token`r`n"
    }
    [System.IO.File]::WriteAllText($ConfigPath, $template, (New-Object System.Text.UTF8Encoding($false)))
    [System.IO.File]::WriteAllText((Join-Path $InstallRoot "ADMIN_TOKEN.txt"), $token, (New-Object System.Text.UTF8Encoding($false)))
}

$ConfigText = Get-Content $ConfigPath -Raw -Encoding UTF8
$ConfigReady = ($ConfigText -notmatch "http://internal-llm-gateway/v1") -and ($ConfigText -match "(?m)^WIICON5_LLM_API_KEY=.+$")
if ($ConfigReady) {
    $Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$InstallRoot\run-bot.cmd`""
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    $Settings = New-ScheduledTaskSettingsSet -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    $Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
    if (-not (Get-NetFirewallRule -DisplayName "WIICON ChatBot 5" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName "WIICON ChatBot 5" -Direction Inbound -Protocol TCP -LocalPort $ServicePort -Action Allow | Out-Null
    }
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Service started."
} else {
    Write-Warning "LLM settings are incomplete. Create server.env next to install.cmd and run the installer again."
}

Write-Host "Installation completed."
Write-Host "Configuration: $ConfigPath"
Write-Host "Administrative token: $InstallRoot\ADMIN_TOKEN.txt"
Write-Host "Update inbox: $InstallRoot\updates\inbox"
Write-Host "Web interface: http://${ServerName}:${ServicePort}/"

if ($StagedSourceRoot -and (Test-Path $StagedSourceRoot)) {
    Remove-Item $StagedSourceRoot -Recurse -Force -ErrorAction SilentlyContinue
}
