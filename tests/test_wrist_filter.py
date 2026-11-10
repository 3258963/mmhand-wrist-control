"""wrist_filter 测试：语义与 mmhand_scope 原 _encoder_filter_update 逐行为一致。

预热期（窗口<5）：输出=原值；窗口满：med=中值，ema += ALPHA·(med−ema)，
ema 由预热期最后一个原值种子（不是由中值种子）。
"""
import pytest

from wrist_filter import (
    ENCODER_COUNTS_PER_TURN,
    FILTER_ALPHA,
    FILTER_MEDIAN_N,
    WristAxisFilter,
    unwrap_counts,
)


def test_constants():
    assert FILTER_MEDIAN_N == 5
    assert FILTER_ALPHA == pytest.approx(0.10)   # 2026-11-05 方案 B 上调


def test_prewarm_passthrough():
    f = WristAxisFilter()
    for raw in (100.0, 200.0, 300.0, 400.0):
        assert f.update(raw) == raw


def test_spike_rejected():
    f = WristAxisFilter()
    for _ in range(FILTER_MEDIAN_N - 1):
        f.update(100.0)
    out = f.update(1000.0)   # 第 5 拍：中值窗口含尖峰，中值仍 100
    assert out == pytest.approx(100.0)


def test_ema_converge():
    f = WristAxisFilter()
    outs = [f.update(100.0) for _ in range(30)]
    assert outs[0] == 100.0
    for v in outs:
        assert v == pytest.approx(100.0)   # 恒定输入输出恒定，无漂移


def test_reset():
    f = WristAxisFilter()
    for _ in range(10):
        f.update(100.0)
    f.reset()
    assert f.update(7000.0) == 7000.0   # 回到预热态


def test_ema_seeded_by_last_prewarm_value():
    """预热末值 400 种子 EMA：第 5 拍 med=300（窗口 200..400→中值300）
    → 输出 400+ALPHA·(300−400)，证明种子语义与 scope 一致。"""
    f = WristAxisFilter()
    for raw in (100.0, 200.0, 300.0, 400.0):
        f.update(raw)
    out = f.update(300.0)
    assert out == pytest.approx(400.0 + FILTER_ALPHA * (300.0 - 400.0))


# ---------- unwrap_counts 过圈解绕（2026-10-28） ----------

def test_unwrap_forward_wrap():
    """raw 上行过圈（16383→0）：解绕到 prev 所在圈，恢复连续表示。"""
    assert unwrap_counts(3.0, 16380.0) == pytest.approx(16387.0)


def test_unwrap_backward_wrap():
    """raw 下行过圈（0→16383）：同样恢复连续。"""
    assert unwrap_counts(16380.0, 3.0) == pytest.approx(-4.0)


def test_unwrap_noop_when_close():
    """同圈内的正常采样不被改动。"""
    assert unwrap_counts(5000.0, 5100.0) == pytest.approx(5000.0)


def test_wrap_full_chain_continuous():
    """端到端：过圈扫掠经 解绕+中值5+EMA 后，相对角连续且收敛到真值。

    复现消费端数学（mmhand_scope._axis_deg/_angle_delta）：
    deg = (raw/16384·180+180)%360−180；rel = (deg−base+180)%360−180。
    基准 raw=16300，正向扫 +300 counts 过绕回点：旧链路（不解绕）在过圈
    处 rel 会跳 ~−176°；解绕后单拍变化 ≤ 物理步进（10 counts≈0.11°），
    保持后收敛到 +300·180/16384 ≈ +3.296°。
    """
    period = 16384.0
    s = 180.0 / period

    def deg(x):
        return (x / period * 180.0 + 180.0) % 360.0 - 180.0

    def rel(cur, base):
        return (cur - base + 180.0) % 360.0 - 180.0

    base_raw = 16300.0
    filt = WristAxisFilter()
    out_prev = None
    rels = []
    samples = [base_raw + 10 * k for k in range(1, 31)] + [16600.0] * 200
    for x in samples:
        raw = x % period   # 通道里看到的是绕回后的单圈 raw
        if out_prev is not None:
            raw = unwrap_counts(raw, out_prev)
        out_prev = filt.update(raw)
        rels.append(rel(deg(out_prev), deg(base_raw)))

    max_step = max(abs(b - a) for a, b in zip(rels, rels[1:]))
    assert max_step < 0.2   # 单拍最大变化远小于半圈级跳变（旧链路 ~176°）
    assert rels[-1] == pytest.approx(300 * s, abs=0.01)
