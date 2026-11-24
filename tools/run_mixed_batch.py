"""混合模式：固定 C1 参数，扫 C2/C3（角度）参数。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
SCRIPT = os.path.join(ROOT, "tools", "auto_mixed.py")
EXP = os.path.join(ROOT, "run_data", "scope_exports")

C1 = dict(C1N="2.0", C1KP="15", C1KI="20", C1ILIM="20", C1STEP="120", C1FF="0")
CONFIGS = [
    dict(tag="N1_kp10_ff00_step20", POSKP="0.10", POSFF="0.00", POSSTEP="20"),
    dict(tag="N2_kp15_ff00_step30", POSKP="0.15", POSFF="0.00", POSSTEP="30"),
    dict(tag="N3_kp10_ff15_step30", POSKP="0.10", POSFF="0.15", POSSTEP="30"),
    dict(tag="N4_kp20_ff15_step40", POSKP="0.20", POSFF="0.15", POSSTEP="40"),
]


def main() -> int:
    for c in CONFIGS:
        env = dict(os.environ)
        env.update(C1)
        env.update({k: v for k, v in c.items() if k != "tag"})
        print(f"=== {c['tag']}  angle kp={c['POSKP']} ff={c['POSFF']} step={c['POSSTEP']}", flush=True)
        r = subprocess.run([PY, SCRIPT], env=env, capture_output=True, text=True, timeout=300)
        for line in (r.stdout or "").splitlines()[-6:]:
            print("   ", line, flush=True)
        if r.returncode != 0:
            print("   rc", r.returncode, (r.stderr or "")[-200:], flush=True)
        src = os.path.join(EXP, "mixed_test.csv")
        if os.path.exists(src) and os.path.getsize(src) > 200:
            dst = os.path.join(EXP, f"mixed_{c['tag']}.csv")
            shutil.copyfile(src, dst)
            print("    saved", os.path.basename(dst), flush=True)
        else:
            print("    WARN empty", flush=True)
        time.sleep(2)
    print("=== MIXED BATCH DONE ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
