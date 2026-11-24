import csv
import math
import time

import pytest
from PySide6.QtWidgets import QApplication

import mmhand_scope as scope
import mmhand_scope_export
from wrist_control_law import WristCalib
from wrist_model import wrist_eval
from wrist_tension_estimate import elastic_extension_m, static_c23_tensions


def test_static_reflects_layout_change_and_uses_input_torque():
    start = wrist_eval(0.0, 0.0)
    end = wrist_eval(0.0, math.radians(5.0))
    base = static_c23_tensions(start.r_m, 5.0, (0.0, 0.0))
    at_end = static_c23_tensions(end.r_m, 5.0, (0.0, 0.0))
    assert base == pytest.approx((11.24857641, 14.35212898))
    assert tuple(b - a for a, b in zip(base, at_end)) == pytest.approx((0.89904805, 1.14113290))

    expected = (5.0, 12.0, 15.0)
    required = tuple(sum(r * f for r, f in zip(row, expected)) for row in end.r_m)
    assert static_c23_tensions(end.r_m, expected[0], required) == pytest.approx(expected[1:])
    with pytest.raises(ValueError, match="奇异"):
        static_c23_tensions([[0, 1, 2], [0, 2, 4]], 5.0, (0.0, 0.0))


def test_elastic_extension_uses_signed_spool_conversion():
    assert elastic_extension_m(0.051, 0.050, 880, 1000, -120_000) == pytest.approx(0)
    assert elastic_extension_m(0.050, 0.050, 1120, 1000, -120_000) == pytest.approx(0.001)


def test_observation_tab_compares_only_confirmed_sensors_and_exports(monkeypatch, tmp_path):
    monkeypatch.setattr(scope, "load_layout_json", lambda: {})
    monkeypatch.setattr(mmhand_scope_export, "EXPORT_DIR", tmp_path)
    app = QApplication.instance() or QApplication([])
    window = scope.ScopeWindow(default_port="COM_TEST")
    window.connected = True
    window.wrist_calib = WristCalib([-120_000.0] * 3, [0.0, 0.0])
    window._tension_sensor = object()
    window._tension_ch_map = [1, 2, 3]
    window.t0 = time.monotonic() - 1.0
    window.angle_baseline[16] = 0.0
    window.angle_baseline[17] = 0.0
    model = wrist_eval(0.0, 0.0)
    monkeypatch.setattr(window, "_r_at_current", lambda: (0.0, 0.0, model, 0.0, 0.0))

    def feed(m28, m29, f2, f3):
        now = time.monotonic()
        window._tension_last = (now, [5.0, f2, f3])
        for key, value in (("enc_raw_16", 0), ("enc_raw_17", 0),
                           ("m28_abs", m28), ("m29_abs", m29)):
            window.channels[key].buf.append(now - window.t0, value)

    try:
        window._toggle_rt_window()
        observer = window.rt_window
        panel = observer.estimate_panel
        observer.tabs.setCurrentWidget(panel)
        app.processEvents()
        feed(1000, 2000, 11.1, 14.2)
        for edit in panel.tau_edits:
            edit.setText("0")
        panel.k_edits[0].setText("5")
        panel._capture_reference()
        assert panel.live_cells[0][0].text() == "—"
        assert panel.live_cells[0][2].text() == "11.249"
        assert panel.live_cells[1][2].text() == "—"
        panel._sensor_checks[0].setChecked(True)
        feed(1120, 2000, 16.0, 14.2)
        panel.refresh(window._r_at_current())
        assert panel.live_cells[0][2].text() == "16.249"
        assert panel.live_cells[0][3].text() == "0.249"
        panel._capture_point()
        assert "0.249 N" in panel.summary.text()
        panel._export()
        with next(tmp_path.glob("wrist_tension_compare_*.csv")).open(encoding="utf-8-sig") as file:
            row = next(csv.DictReader(file))
        assert float(row["c2_elastic_err_n"]) == pytest.approx(0.24858)
        assert float(row["c2_baseline_counts"]) == pytest.approx(1000)
        assert math.isnan(float(row["c3_meas_n"]))
        assert math.isnan(float(row["c3_static_err_n"]))

        window.t0 -= 0.5
        feed(1120, 2000, 16.0, 14.2)
        panel._last_refresh = -math.inf
        panel.refresh(window._r_at_current())
        assert panel.live_cells[0][2].text() == "—"
    finally:
        window._tension_sensor = None
        window.close()
        app.processEvents()
