# -*- coding: utf-8 -*-
import pathlib

p = pathlib.Path(r"E:\SLAHAND\mmhand_wrist_control_1.0\code\mmhand-main\mmhand_scope.py")
kws = ["def _force_params_v2", "def _cl_tick_tight", "def _apply_force_step",
       "def _tension_params", "def _tight_params", "def _cl_tick_force",
       "MOTOR_SOFT_LIMIT =", "def _tension_guard", "def _cl_tick_tension"]
for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
    for kw in kws:
        if kw in line:
            print(i, line.strip()[:100])
