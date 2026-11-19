"""绘图脚本公共底座（2026-11-19 抽出）。

以前 7 个 `gen_*.py` 各自重复这几行：

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    INK, MUTED, GRID = "#24303f", "#6b7785", "#dfe4ea"

现在统一从这里导入：

    from tools._figbase import INK, MUTED, GRID, plt

导入本模块即已完成「Agg 后端 + 中文字体 + 负号显示」三件事，
所以**必须在本模块之后**再 `import matplotlib.pyplot`（一般不需要，直接用 `plt`）。

注意：导入顺序有讲究 —— `matplotlib.use("Agg")` 必须在 pyplot 首次导入之前生效，
所以脚本里不要再自己 `import matplotlib.pyplot`。
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.autolayout"] = False

# 全仓统一配色（与 docs/ 里的插图一致）
INK = "#24303f"
MUTED = "#6b7785"
GRID = "#dfe4ea"
BLUE = "#3b82f6"
RED = "#ef4444"
GREEN = "#10b981"
AMBER = "#f59e0b"
PURPLE = "#8b5cf6"

__all__ = ["plt", "INK", "MUTED", "GRID", "BLUE", "RED", "GREEN", "AMBER",
           "PURPLE"]
