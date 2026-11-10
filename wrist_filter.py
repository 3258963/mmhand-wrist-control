"""腕部轴角滤波 —— 中值 N + EMA 低通，纯函数式模块（可移植）。

从 mmhand_scope.py 的 _encoder_filter_update 原样抽出（2026-10-25），
语义逐行为一致；STM32 侧按本文件逐行翻译成 C。

滤波链设计依据（实测，2026-10-23）：电机上电保持时噪声 std≈1.0~1.4°，
中值5 砍 EMI 尖峰 + EMA 压宽带噪声（α=0.03 时实测压到 ≈0.13°，低于闭环
死区 0.3°）。2026-10-28 α 由 0.03 上调至 0.05（≈150ms@128Hz），响应更快、
噪声略升；α 越小越稳但响应越慢。
2026-11-05 α 由 0.05 上调至 0.10（用户拍板，方案 B）：时间常数 150ms→76ms
（@131Hz），反馈链滞后减半——力控/扫掠响应收益；链路噪声模型估 0.12~0.17°，
仍低于闭环死区 0.3°（上台架按三步验证：静止 std/放手整定/小阶跃无抖动）。

输入是磁编 raw counts（0..16383，14bit）。raw 跨 0/16383 绕回点时须先经
unwrap_counts 解绕到同一圈表示再滤波（2026-10-28：编码器重接线后零位可能
落在绕回点附近，原"工作角窄不会跨绕回"假设不再成立，解绕后中值/EMA 与
下游角度差全程连续）。前提：相邻两拍物理角差 < 8192 counts（半圈），
腕部两轴工作角远小于此。

对应 C 结构：
    typedef struct {
        float  buf[5];      /* 定长中值窗口 */
        uint8_t n;          /* 已填入样本数 */
        float  ema;         /* EMA 状态，预热期跟随原值 */
    } wrist_axis_filter_t;

    void wrist_axis_filter_reset(wrist_axis_filter_t *f);
    float wrist_axis_filter_update(wrist_axis_filter_t *f, float raw);
    float wrist_unwrap_counts(float raw, float prev);   /* period=16384 */
"""
from __future__ import annotations

FILTER_MEDIAN_N = 5
FILTER_ALPHA = 0.10   # 2026-11-05 由 0.05 上调（方案 B）：τ 150→76ms@131Hz
ENCODER_COUNTS_PER_TURN = 16384.0


def unwrap_counts(raw: float, prev: float,
                  period: float = ENCODER_COUNTS_PER_TURN) -> float:
    """把 raw 解绕到 prev 附近（同一圈表示）：raw + period·k，k 取与 prev 最近。

    单圈编码器 raw 过圈时跳变 ±period；|raw−prev| < period/2 时（相邻两拍
    物理角差小于半圈）解绕结果唯一且连续，可直接进中值/EMA 与角度差。
    prev 为上一拍滤波输出（解绕域）；首轮无 prev 时调用方直接用原 raw。
    """
    return raw + period * round((prev - raw) / period)


class WristAxisFilter:
    """单轴滤波器：中值 FILTER_MEDIAN_N + EMA FILTER_ALPHA。

    预热期（窗口未满）输出原值且 EMA 跟随原值；窗口满后
    ema += ALPHA·(median−ema)（EMA 由预热期最后一个原值种子）。
    状态全部在实例内，reset 回到预热态。
    """

    __slots__ = ("_buf", "_ema")

    def __init__(self) -> None:
        self._buf: list[float] = []
        self._ema: float | None = None

    def reset(self) -> None:
        self._buf = []
        self._ema = None

    def update(self, raw: float) -> float:
        buf = self._buf
        buf.append(raw)
        if len(buf) > FILTER_MEDIAN_N:
            del buf[0]
        if len(buf) < FILTER_MEDIAN_N:
            self._ema = raw  # 预热期直接用原值
            return raw
        med = sorted(buf)[FILTER_MEDIAN_N // 2]
        cur = self._ema
        self._ema = med if cur is None else cur + FILTER_ALPHA * (med - cur)
        return self._ema
