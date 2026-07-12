$ErrorActionPreference = "Stop"

$SourceRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallRoot = "C:\ProgramData\WiiconChatBot5"
$TaskName = "WiiconChatBot5"

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

Write-Host "Установка WIICON ChatBot 5 в $InstallRoot"
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask -and $ExistingTask.State -eq "Running") {
    Stop-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 3
}
New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
foreach ($directory in @("app", "runtime", "data", "config", "logs", "updates\inbox", "updates\applied", "updates\failed")) {
    New-Item -ItemType Directory -Path (Join-Path $InstallRoot $directory) -Force | Out-Null
}

if (Test-Path (Join-Path $InstallRoot "app\current")) {
    $backup = Join-Path $InstallRoot "app\preinstall-backup"
    if (Test-Path $backup) { Remove-Item $backup -Recurse -Force }
    Move-Item (Join-Path $InstallRoot "app\current") $backup
}
Copy-Item (Join-Path $SourceRoot "app\current") (Join-Path $InstallRoot "app\current") -Recurse -Force
Copy-Item (Join-Path $SourceRoot "runtime\*") (Join-Path $InstallRoot "runtime") -Recurse -Force
Copy-NewFilesOnly (Join-Path $SourceRoot "data_seed") (Join-Path $InstallRoot "data")

foreach ($file in @("run-bot.cmd", "apply-update.cmd")) {
    Copy-Item (Join-Path $SourceRoot $file) (Join-Path $InstallRoot $file) -Force
}

$ConfigPath = Join-Path $InstallRoot "config\.env.wiicon5"
$ProvidedConfig = Join-Path $SourceRoot "server.env"
if ((Test-Path $ProvidedConfig) -or (-not (Test-Path $ConfigPath))) {
    $templatePath = if (Test-Path $ProvidedConfig) { $ProvidedConfig } else { Join-Path $SourceRoot "server.env.example" }
    $template = Get-Content $templatePath -Raw
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

$ConfigText = Get-Content $ConfigPath -Raw
$ConfigReady = ($ConfigText -notmatch "http://internal-llm-gateway/v1") -and ($ConfigText -match "(?m)^WIICON5_LLM_API_KEY=.+$")
if ($ConfigReady) {
    $Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$InstallRoot\run-bot.cmd`""
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    $Settings = New-ScheduledTaskSettingsSet -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    $Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
    if (-not (Get-NetFirewallRule -DisplayName "WIICON ChatBot 5" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName "WIICON ChatBot 5" -Direction Inbound -Protocol TCP -LocalPort 7786 -Action Allow | Out-Null
    }
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Сервис запущен."
} else {
    Write-Warning "Параметры LLM не заполнены. Создайте server.env рядом с install.cmd и повторно запустите installer."
}

Write-Host "Установка завершена."
Write-Host "Конфигурация: $ConfigPath"
Write-Host "Административный токен: $InstallRoot\ADMIN_TOKEN.txt"
Write-Host "Каталог входящих обновлений: $InstallRoot\updates\inbox"
Write-Host "Web-интерфейс: http://АДРЕС-СЕРВЕРА:7786/"
