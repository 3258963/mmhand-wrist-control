"""已删除（2026-11-23）：重力标定/弹簧辨识的测试随之移除。

τ_ff 改为界面直接输入（`tau_ff_r` / `tau_ff_p`），相关行为由
`tests/test_impedance.py`（`tau_ff` 项参与 `τ = K·e + τ_ff`）覆盖。

可直接删掉：`del wrist_gravity.py tests\\test_wrist_gravity.py`
"""
