from dataclasses import replace

from wrist_hybrid_control import C1TensionParams, C1TensionState, c1_tension_target


PARAMS = C1TensionParams(target_n=5.0, kp=0.0, ki=0.0, kd=0.0, ff_gain=0.0,
                         max_step=5, travel=100, i_limit=5.0, min_n=0.2, max_n=25.0)


def step(params, state, *, force=5.0, time=1.0, counts=1000):
    return c1_tension_target(params, state, force_n=force, force_time=time,
                             length_m=0.05, counts=counts, origin=1000,
                             spool_k=-108649.77, dt=0.01)


def test_c1_derivative_uses_new_force_feedback():
    params = replace(PARAMS, kd=0.2)
    state = C1TensionState()
    assert step(params, state).pid_counts == 0.0
    # 目标阶跃、旧采样重用均不产生新的微分。
    assert step(replace(params, target_n=5.5), state).pid_counts == 0.0
    release = step(params, state, force=6.0, time=1.05)
    assert release.counts < 1000
    assert step(params, state, force=6.0, time=1.05).pid_counts == release.pid_counts


def test_c1_integral_respects_travel_and_disables_live():
    params = replace(PARAMS, ki=100.0)
    state = C1TensionState()
    limited = step(params, state, force=4.0, counts=1100)
    assert limited.counts == 1100
    assert limited.travel_limited
    assert state.i_counts == 0.0
    assert step(params, state, force=4.0).counts == 1001
    disabled = step(replace(params, ki=0.0), state, force=4.0)
    assert disabled.counts == 1000
    assert state.i_counts == 0.0
