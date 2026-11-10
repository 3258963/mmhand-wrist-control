$ErrorActionPreference = 'Continue'
$log = Join-Path $PSScriptRoot 'latency_fix.log'
"=== run $(Get-Date) user=$(whoami)" | Out-File $log -Encoding utf8
reg add "HKLM\SYSTEM\CurrentControlSet\Enum\FTDIBUS\VID_0403+PID_6001+00000000A\0000\Device Parameters" /v LatencyTimer /t REG_DWORD /d 1 /f 2>&1 | Out-File $log -Append -Encoding utf8
pnputil /restart-device "FTDIBUS\VID_0403+PID_6001+00000000A\0000" 2>&1 | Out-File $log -Append -Encoding utf8
$v = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Enum\FTDIBUS\VID_0403+PID_6001+00000000A\0000\Device Parameters' -Name LatencyTimer).LatencyTimer
"after: LatencyTimer=$v" | Out-File $log -Append -Encoding utf8
