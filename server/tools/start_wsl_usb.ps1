param(
    [string]$Distribution='Ubuntu',
    [Parameter(Mandatory=$true)][string]$AdbPath,
    [string]$Serial
)
$ErrorActionPreference='Stop'
if (-not (Test-Path -LiteralPath $AdbPath)) { throw 'Pass the installed platform-tools adb path with -AdbPath' }
if (-not $Serial) {
    $connected = @(& $AdbPath devices | Select-Object -Skip 1 | Where-Object { $_ -match '^\S+\s+device$' } | ForEach-Object { ($_ -split '\s+')[0] })
    if ($connected.Count -ne 1) { throw 'Connect exactly one authorized Android device or pass -Serial' }
    $Serial = $connected[0]
}
& wsl -d $Distribution -u root -- systemctl start kakao-radar-api kakao-radar-local-https kakao-radar-analysis kakao-radar-delivery
if ($LASTEXITCODE -ne 0) { throw 'WSL service startup failed' }
& $AdbPath -s $Serial reverse tcp:8443 tcp:8443
if ($LASTEXITCODE -ne 0) { throw 'USB forwarding failed' }
& $AdbPath -s $Serial shell am start -W -n dev.kakaoradar.collector/.AdbBootstrapActivity | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Collector bootstrap failed' }
$status = & $AdbPath -s $Serial shell am broadcast --include-stopped-packages -a dev.kakaoradar.collector.CONTROL -n dev.kakaoradar.collector/.AdbControlReceiver --es command status
if ($LASTEXITCODE -ne 0 -or (($status -join ' ') -notmatch 'data=')) { throw 'Collector status command failed' }
Write-Output 'WSL services started; USB HTTPS forwarding restored'
