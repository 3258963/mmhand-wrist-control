"""观测台里的三绳张力对比。仅读反馈，试验基准属于当前观测台会话。"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime
from statistics import fmean

from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from mmhand_scope_export import dump_csv
from wrist_force_law import F_SENSOR_MIN_N, STALE_MS
from wrist_model import PITCH, ROLL, WristModelOut
from wrist_tension_estimate import elastic_extension_m, static_c23_tensions, tension_error_n


NAN = math.nan
MAX_SAMPLE_SKEW_S = 0.10


@dataclass(frozen=True)
class _Sample:
    t_s: float
    pose_deg: tuple[float, float]
    model: WristModelOut
    f1_n: float
    measured_n: tuple[float, float]
    counts: tuple[float, float]
    spool: tuple[float, float]
    reference_key: tuple

    def length_m(self, cable: int) -> float:
        return self.model.s_m[ROLL][cable] + self.model.s_m[PITCH][cable]


class TensionEstimatePanel(QWidget):
    def __init__(self, scope):
        super().__init__()
        self.scope = scope
        self._reference = None
        self._last_refresh = -math.inf
        self._records = []
        self._confirmed_channels = [None, None]
        self._sensor_checks = []

        layout = QVBoxLayout(self)
        setup = QGroupBox("基准与绳刚度")
        form = QGridLayout(setup)
        hint = QLabel("腕部停稳后，填写该姿态两轴所需合成绳力矩（R 矩阵的符号，含重力与外载），再采基准。")
        hint.setWordWrap(True)
        form.addWidget(hint, 0, 0, 1, 4)
        self.tau_edits = self._fields(form, 1, ("Roll 力矩 (N·m)", "Pitch 力矩 (N·m)"))
        self.k_edits = self._fields(form, 2, ("C2 刚度 (N/mm)", "C3 刚度 (N/mm)"),
                                    scope._tension_estimate_k)
        for edit in self.k_edits:
            edit.setPlaceholderText("选填，实测标定")
            edit.editingFinished.connect(self._save_stiffness)
        controls = QHBoxLayout()
        for text, action in (("采集张力基准", self._capture_reference),
                             ("记录当前对比点", self._capture_point),
                             ("导出对比 CSV", self._export)):
            button = QPushButton(text)
            button.clicked.connect(action)
            controls.addWidget(button)
        controls.addStretch(1)
        form.addLayout(controls, 3, 0, 1, 4)
        layout.addWidget(setup)

        live = QGroupBox("当前反馈与短时弹性预估")
        grid = QGridLayout(live)
        self.live_cells = self._table(grid, ("实测 (N)", "基准 (N)", "预估 (N)",
                                             "预估 − 实测 (N)", "绳长差 (mm)"))
        for i, cable in enumerate(("C2", "C3")):
            box = QCheckBox(f"{cable} 已接入实测传感器")
            box.setToolTip("接好并校准传感器后勾选。实测列使用绝对张力。")
            box.toggled.connect(lambda checked, idx=i: self._confirm_sensor(idx, checked))
            grid.addWidget(box, 3, 1 + i * 2, 1, 2)
            self._sensor_checks.append(box)
        self.live_status = QLabel("等待腕部和 C1 反馈")
        grid.addWidget(self.live_status, 4, 0, 1, 6)
        layout.addWidget(live)

        saved = QGroupBox("最近一次静力反算")
        grid = QGridLayout(saved)
        self.static_cells = self._table(grid, ("实测 (N)", "静力反算 (N)", "反算 − 实测 (N)"))
        self.point_status = QLabel("停稳后记录对比点。填写该点已知的两轴力矩可同时做静力反算。")
        self.point_status.setWordWrap(True)
        grid.addWidget(self.point_status, 3, 0, 1, 4)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        grid.addWidget(self.summary, 4, 0, 1, 4)
        layout.addWidget(saved)
        layout.addStretch(1)

    @staticmethod
    def _fields(grid, row, names, values=("", "")):
        edits = []
        for i, (name, value) in enumerate(zip(names, values)):
            grid.addWidget(QLabel(name), row, i * 2)
            edit = QLineEdit(value)
            grid.addWidget(edit, row, i * 2 + 1)
            edits.append(edit)
        return edits

    @staticmethod
    def _table(grid, columns):
        for col, label in enumerate(columns, 1):
            grid.addWidget(QLabel(label), 0, col)
        cells = []
        for row, cable in enumerate(("C2", "C3"), 1):
            grid.addWidget(QLabel(cable), row, 0)
            values = [QLabel("—") for _ in columns]
            for col, value in enumerate(values, 1):
                grid.addWidget(value, row, col)
            cells.append(values)
        return cells

    @staticmethod
    def _fill(cells, rows):
        for widgets, values in zip(cells, rows):
            for widget, value in zip(widgets, values):
                widget.setText(f"{value:.3f}" if math.isfinite(value) else "—")

    @staticmethod
    def _number(edit):
        try:
            return float(edit.text().strip().replace("−", "-"))
        except ValueError:
            return NAN

    def _save_stiffness(self):
        values = [edit.text().strip() for edit in self.k_edits]
        if values != self.scope._tension_estimate_k:
            self.scope._tension_estimate_k = values
            self.scope._save_layout()

    def _confirm_sensor(self, idx, checked):
        self._confirmed_channels[idx] = self.scope._tension_ch_map[idx + 1] if checked else None
        self._last_refresh = -math.inf

    def channel_changed(self, cable_idx):
        if cable_idx == 0:
            self.invalidate_reference()
        else:
            self._sensor_checks[cable_idx - 1].setChecked(False)

    def invalidate_reference(self):
        self._reference = None
        self._fill(self.static_cells, ((NAN, NAN, NAN),) * 2)
        self.point_status.setText("反馈或标定已变更，请重新采集张力基准。")
        self._last_refresh = -math.inf

    def _sample(self, pose):
        scope = self.scope
        last = scope._tension_last
        calib = scope.wrist_calib
        now = time.monotonic()
        if (scope._tension_sensor is None or last is None
                or not (0.0 <= now - last[0] <= STALE_MS / 1000)):
            raise ValueError("等待新鲜的 C1 张力")
        if not scope.connected or scope.t0 is None or pose is None or calib is None:
            raise ValueError("等待腕部磁编、卷筒反馈和标定")
        roll, pitch, model, _, _ = pose
        if not model.angle_in_range or not all(map(math.isfinite, (roll, pitch))):
            raise ValueError("当前姿态超出模型范围")
        rel_now = now - scope.t0
        f_time = last[0] - scope.t0
        enc = [scope.channels[key].buf.last_sample() for key in ("enc_raw_16", "enc_raw_17")]
        if not all(0.0 <= rel_now - t <= STALE_MS / 1000 and math.isfinite(v) for t, v in enc):
            raise ValueError("磁编反馈无效或已过期")
        stamps = (enc[0][0], enc[1][0], f_time)
        if max(stamps) - min(stamps) > MAX_SAMPLE_SKEW_S:
            raise ValueError("磁编和张力采样时间差过大")
        c1, *raw_measured = last[1]
        if not math.isfinite(c1) or c1 < F_SENSOR_MIN_N:
            raise ValueError("C1 实测张力无效")
        channels = tuple(scope._tension_ch_map)
        measured = tuple(value if (channels[i + 1] == confirmed
                                   and channels.count(confirmed) == 1
                                   and math.isfinite(value) and value >= F_SENSOR_MIN_N)
                         else NAN for i, (confirmed, value) in
                         enumerate(zip(self._confirmed_channels, raw_measured)))
        spool = tuple(calib.k_counts_per_m[1:])
        counts = []
        for i, key in enumerate(("m28_abs", "m29_abs")):
            t, value = scope.channels[key].buf.last_sample()
            sample_stamps = (*stamps, t)
            is_aligned = max(sample_stamps) - min(sample_stamps) <= MAX_SAMPLE_SKEW_S
            valid = (0.0 <= rel_now - t <= STALE_MS / 1000 and is_aligned
                     and math.isfinite(value) and math.isfinite(spool[i]) and spool[i] != 0)
            counts.append(value if valid else NAN)
        reference_key = (scope.t0, tuple(scope.angle_baseline[j] for j in (16, 17)),
                         tuple(calib.zero_offset_deg), spool, channels[0], id(scope._tension_sensor))
        if self._reference is not None and self._reference[0].reference_key != reference_key:
            self.invalidate_reference()
        return _Sample(f_time, (roll, pitch), model, c1, measured, tuple(counts),
                       spool, reference_key)

    def _elastic(self, sample):
        if self._reference is None:
            return (NAN, NAN), (NAN, NAN), (NAN, NAN)
        reference, forces0 = self._reference
        residual_mm = tuple(1000 * elastic_extension_m(
            sample.length_m(i + 1), reference.length_m(i + 1),
            sample.counts[i], reference.counts[i], sample.spool[i])
            if math.isfinite(sample.counts[i]) else NAN for i in range(2))
        stiffness = tuple(self._number(edit) for edit in self.k_edits)
        forces = tuple(
            f0 + k * dx if math.isfinite(k) and k > 0 else NAN
            for f0, k, dx in zip(forces0, stiffness, residual_mm))
        return forces0, forces, residual_mm

    def refresh(self, pose):
        if not self.isVisible():
            return
        now = time.monotonic()
        if now - self._last_refresh < 0.05:
            return
        self._last_refresh = now
        try:
            sample = self._sample(pose)
        except ValueError as exc:
            self._fill(self.live_cells, ((NAN,) * 5,) * 2)
            self.live_status.setText(str(exc))
            return
        forces0, elastic, residual = self._elastic(sample)
        rows = []
        for measured, f0, f, dx in zip(sample.measured_n, forces0, elastic, residual):
            value = f if f > 0 else NAN
            rows.append((measured, f0, value, tension_error_n(value, measured), dx))
        self._fill(self.live_cells, rows)
        status = f"C1 实测 {sample.f1_n:.3f} N"
        if self._reference is None:
            status += " ｜ 等待采集基准"
        elif any(f <= 0 for f in elastic):
            cables = "、".join(f"C{i + 2}" for i, f in enumerate(elastic) if f <= 0)
            status += f" ｜ {cables} 可能松绳"
        if self._reference is not None:
            if any(math.isnan(count) for count in sample.counts):
                status += " ｜ 等待有效且同时间段的卷筒反馈"
            if any(not (0 < self._number(edit) < math.inf) for edit in self.k_edits):
                status += " ｜ 待填写对应绳的标定刚度"
        self.live_status.setText(status)

    def _show_static(self, sample, forces, title):
        self._fill(self.static_cells, [(m, f, tension_error_n(f, m))
                                      for m, f in zip(sample.measured_n, forces)])
        roll, pitch = sample.pose_deg
        f_min, f_max, limits_ok = self.scope._effective_flimits()
        outside = limits_ok and any(f < f_min or f > f_max for f in forces)
        note = " ｜ 反算张力超出配置范围" if outside else ""
        self.point_status.setText(f"{title} · Roll {roll:+.2f}° / Pitch {pitch:+.2f}°{note}")

    def _capture_reference(self):
        try:
            sample = self._sample(self.scope._r_at_current())
            if not all(map(math.isfinite, sample.counts)):
                raise ValueError("采集基准需要有效且同时间段的 M28/M29 多圈反馈")
            torque = tuple(self._number(edit) for edit in self.tau_edits)
            forces = static_c23_tensions(sample.model.r_m, sample.f1_n, torque)
        except ValueError as exc:
            self.point_status.setText(str(exc))
            return
        self._reference = (sample, forces)
        self._show_static(sample, forces, "已采基准")
        self._last_refresh = -math.inf
        self.refresh(self.scope._r_at_current())

    def _capture_point(self):
        try:
            sample = self._sample(self.scope._r_at_current())
            torque = tuple(self._number(edit) for edit in self.tau_edits)
            have_tau = any(edit.text().strip() for edit in self.tau_edits)
            static = (static_c23_tensions(sample.model.r_m, sample.f1_n, torque)
                      if have_tau else (NAN, NAN))
            forces0, raw_elastic, residual = self._elastic(sample)
            elastic = tuple(f if f > 0 else NAN for f in raw_elastic)
            if self._reference is None and not have_tau:
                raise ValueError("请填写该静止点的两轴力矩，或先采集张力基准")
        except ValueError as exc:
            self.point_status.setText(str(exc))
            return
        self._show_static(sample, static, "已记录静止点" if have_tau else "已记录弹性预估点")
        roll, pitch = sample.pose_deg
        reference = self._reference[0] if self._reference is not None else None
        record = {"t_s": sample.t_s, "roll_deg": roll, "pitch_deg": pitch,
                  "c1_meas_n": sample.f1_n, "tau_roll_model_nm": torque[0],
                  "tau_pitch_model_nm": torque[1],
                  "baseline_t_s": reference.t_s if reference else NAN,
                  "baseline_roll_deg": reference.pose_deg[0] if reference else NAN,
                  "baseline_pitch_deg": reference.pose_deg[1] if reference else NAN,
                  "baseline_c1_n": reference.f1_n if reference else NAN}
        for i, c in enumerate(("c2", "c3")):
            measured = sample.measured_n[i]
            record.update({f"{c}_meas_n": measured, f"{c}_baseline_n": forces0[i],
                           f"{c}_static_n": static[i], f"{c}_elastic_n": elastic[i],
                           f"{c}_static_err_n": tension_error_n(static[i], measured),
                           f"{c}_elastic_err_n": tension_error_n(elastic[i], measured),
                           f"{c}_delta_extension_mm": residual[i],
                           f"{c}_counts": sample.counts[i],
                           f"{c}_baseline_counts": reference.counts[i] if reference else NAN,
                           f"{c}_spool_counts_per_m": sample.spool[i],
                           f"{c}_stiffness_n_mm": self._number(self.k_edits[i])})
        self._records.append(record)
        metrics = []
        for method, label in (("static", "静力"), ("elastic", "弹性")):
            for cable in ("c2", "c3"):
                errors = [r[f"{cable}_{method}_err_n"] for r in self._records]
                valid = [abs(e) for e in errors if math.isfinite(e)]
                if valid:
                    metrics.append(f"{cable.upper()} {label} {fmean(valid):.3f} N（{len(valid)} 点）")
        summary = " ｜ 平均绝对误差 " + " · ".join(metrics) if metrics else " ｜ 等待实测对比"
        self.summary.setText(f"已记录 {len(self._records)} 点{summary}")

    def _export(self):
        if not self._records:
            self.summary.setText("先在腕部停稳后记录对比点。")
            return
        name = datetime.now().strftime("wrist_tension_compare_%Y%m%d_%H%M%S_%f.csv")
        cols = [key for key in self._records[0] if key != "t_s"]
        try:
            path = dump_csv(name, header=cols, t=[r["t_s"] for r in self._records],
                            columns=[[r[key] for r in self._records] for key in cols],
                            value_precision=5)
        except OSError:
            path = None
        self.point_status.setText(f"已导出 {name}" if path else "对比 CSV 导出失败")
