"""三绳腕部的 C2/C3 张力估算。几何使用模型坐标，长度 m，力 N，力矩 N·m。"""
from __future__ import annotations

import math


def static_c23_tensions(r_m, f1_n: float, required_tau_nm) -> tuple[float, float]:
    """用 C1 实测张力和已知的两轴合成绳力矩解两根绳的静力平衡。"""
    (r1, a, b), (p1, c, d) = r_m
    tr, tp = required_tau_nm
    if not all(map(math.isfinite, (r1, p1, a, b, c, d, tr, tp, f1_n))) or f1_n <= 0:
        raise ValueError("需要有效的 C1 正张力和两轴所需绳力矩")
    det = a * d - b * c
    if abs(det) <= 1e-6 * (a * a + b * b + c * c + d * d):
        raise ValueError("C2/C3 力臂矩阵接近奇异")
    roll = tr - r1 * f1_n
    pitch = tp - p1 * f1_n
    forces = ((d * roll - b * pitch) / det, (a * pitch - c * roll) / det)
    if not all(math.isfinite(f) and f > 0 for f in forces):
        raise ValueError("静力解超出两绳张紧区间，请核对载荷和力矩方向")
    return forces


def elastic_extension_m(length_m, length0_m, counts, counts0, spool_counts_per_m):
    """模型绳路变化减电机放绳变化。卷筒系数保留标定符号。"""
    return (length_m - length0_m) - (counts - counts0) / spool_counts_per_m


def tension_error_n(estimated_n: float, measured_n: float) -> float:
    """比较采用预估减实测，缺项在显示和 CSV 中作为无效值。"""
    return estimated_n - measured_n
