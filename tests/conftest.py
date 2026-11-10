from pathlib import Path
import os
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 会话级密闭（2026-11-09 审阅 Important#3）：测试绝不写真取证日志。
# mmhand_scope 在 import 时读该环境变量；conftest 先于所有测试模块加载，
# 所以这里 setdefault 对整个会话生效（含 connected=True 的老测试经
# _reject→_safety 写 GATE_REJECT 的路径）。要看日志行为的测试请直接
# monkeypatch mmhand_scope.safety_log（见 test_scope_reject_dialog.cap_safety）。
os.environ.setdefault("MMHAND_SAFETY_LOG", "0")
