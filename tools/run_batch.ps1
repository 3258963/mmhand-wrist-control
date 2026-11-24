param()
$ErrorActionPreference = 'Continue'
Set-Location 'E:\SLAHAND\mmhand_wrist_control_1.0\code\mmhand-main'
$py = '.\.venv\Scripts\python.exe'
$cfg = @(
  @{ tag='T1_base_ms50_amp8';   kp='0.25'; kff='0.35'; ms='50';  msr='0';  msp='0';  amp='8';  ampp='6' },
  @{ tag='T2_kff50_ms50_amp8';  kp='0.25'; kff='0.50'; ms='50';  msr='0';  msp='0';  amp='8';  ampp='6' },
  @{ tag='T3_kp35_ms50_amp8';   kp='0.35'; kff='0.35'; ms='50';  msr='0';  msp='0';  amp='8';  ampp='6' },
  @{ tag='T4_ms70_amp6';        kp='0.25'; kff='0.35'; ms='70';  msr='0';  msp='0';  amp='6';  ampp='6' },
  @{ tag='T5_peraxis_25_45';    kp='0.25'; kff='0.35'; ms='500'; msr='25'; msp='45'; amp='8';  ampp='6' },
  @{ tag='T6_kp30_kff45_ms60';  kp='0.30'; kff='0.45'; ms='60';  msr='0';  msp='0';  amp='6';  ampp='6' },
  @{ tag='T7_ms50_amp10';       kp='0.25'; kff='0.35'; ms='50';  msr='0';  msp='0';  amp='10'; ampp='8' }
)
foreach ($c in $cfg) {
  Write-Output "=== RUN $($c.tag)  kp=$($c.kp) kff=$($c.kff) ms=$($c.ms) msr=$($c.msr) msp=$($c.msp) amp=$($c.amp)/$($c.ampp) ==="
  $env:KP=$c.kp; $env:KI='0'; $env:KD='0'; $env:KFF=$c.kff
  $env:MAXSTEP=$c.ms; $env:MS_R=$c.msr; $env:MS_P=$c.msp
  $env:LIMIT='12'; $env:AMP_R=$c.amp; $env:AMP_P=$c.ampp
  $env:AXIS='2'; $env:STEP_SEC='8'; $env:SINE_SEC='20'
  $env:FREQS='0.05,0.1,0.2,0.25'
  & $py 'tools\auto_sweep_long.py' 2>&1 | ForEach-Object { Write-Output "  $_" }
  $f = Get-ChildItem 'run_data\scope_exports\diag_pos_*.csv' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($f) {
    Copy-Item $f.FullName ("run_data\scope_exports\test_" + $c.tag + ".csv") -Force
    Write-Output "  saved test_$($c.tag).csv  (from $($f.Name))"
  } else {
    Write-Output "  WARN no diag file"
  }
  Start-Sleep -Seconds 2
}
Write-Output '=== BATCH DONE ==='
