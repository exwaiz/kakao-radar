param(
    [string]$Distribution='Ubuntu',
    [string]$AdbPath,
    [string]$Serial='FYZPL77XO799DAQO'
)
$ErrorActionPreference='Stop'
if (-not $AdbPath) {
    $taskRepository = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
    $taskWorkspace = Split-Path (Split-Path $taskRepository -Parent) -Parent
    $AdbPath = Join-Path $taskWorkspace 'work/android-tools/sdk/platform-tools/adb.exe'
}
if (-not (Test-Path -LiteralPath $AdbPath)) { throw 'Pass the installed platform-tools adb path with -AdbPath' }
& wsl -d $Distribution -u root -- systemctl start kakao-radar-api kakao-radar-local-https kakao-radar-analysis kakao-radar-delivery kakao-radar-retention
if ($LASTEXITCODE -ne 0) { throw 'WSL service startup failed' }
& $AdbPath -s $Serial reverse tcp:8443 tcp:8443
if ($LASTEXITCODE -ne 0) { throw 'USB forwarding failed' }
& $AdbPath -s $Serial shell am start -n dev.kakaoradar.collector/.MainActivity
if ($LASTEXITCODE -ne 0) { throw 'Collector launch failed' }
Write-Output 'WSL services started; USB HTTPS forwarding restored'
