"""顺序跑多组参数（每组一个完整自动测试），结果复制成 test_<tag>.csv。

避免 PowerShell 执行策略问题：用 Python 起子进程 + 环境变量。
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
SCRIPT = os.path.join(ROOT, "tools", "auto_sweep_long.py")
EXP = os.path.join(ROOT, "run_data", "scope_exports")

CONFIGS = [
    dict(tag="V1_kp40_kff50_ms120_amp8", kp="0.40", kff="0.50", ms="120", msr="0", msp="0", amp="8", ampp="8"),
    dict(tag="V2_kp50_kff50_ms120_amp8", kp="0.50", kff="0.50", ms="120", msr="0", msp="0", amp="8", ampp="8"),
    dict(tag="V3_kp40_kff60_ms150_amp8", kp="0.40", kff="0.60", ms="150", msr="0", msp="0", amp="8", ampp="8"),
    dict(tag="V4_kp60_kff60_ms150_amp8", kp="0.60", kff="0.60", ms="150", msr="0", msp="0", amp="8", ampp="8"),
    dict(tag="V5_kp50_kff70_ms100_amp8", kp="0.50", kff="0.70", ms="100", msr="0", msp="0", amp="8", ampp="8"),
]


def newest_diag(after: float) -> str | None:
    best = None
    best_t = after
    for f in glob.glob(os.path.join(EXP, "diag_pos_*.csv")):
        t = os.path.getmtime(f)
        if t > best_t:
            best, best_t = f, t
    return best


def main() -> int:
    for c in CONFIGS:
        env = dict(os.environ)
        env.update({
            "KP": c["kp"], "KI": "0", "KD": "0", "KFF": c["kff"],
            "MAXSTEP": c["ms"], "MS_R": c["msr"], "MS_P": c["msp"],
            "LIMIT": "12", "AMP_R": c["amp"], "AMP_P": c["ampp"],
            "AXIS": "2", "STEP_SEC": "8", "SINE_SEC": "20",
            "FREQS": "0.05,0.1,0.2,0.25",
        })
        print(f"=== RUN {c['tag']}  kp={c['kp']} kff={c['kff']} ms={c['ms']} "
              f"msr={c['msr']} msp={c['msp']} amp={c['amp']}/{c['ampp']}", flush=True)
        t0 = time.time()
        r = subprocess.run([PY, SCRIPT], env=env, capture_output=True, text=True, timeout=600)
        for line in (r.stdout or "").splitlines()[-8:]:
            print("   ", line, flush=True)
        if r.returncode != 0:
            print("   returncode", r.returncode, (r.stderr or "")[-300:], flush=True)
        f = newest_diag(t0)
        if f:
            dst = os.path.join(EXP, f"test_{c['tag']}.csv")
            shutil.copyfile(f, dst)
            print(f"    saved {os.path.basename(dst)}", flush=True)
        else:
            print("    WARN: no new diag file", flush=True)
        time.sleep(2)
    print("=== BATCH DONE ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
