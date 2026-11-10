"""mmhand_scope 的 CSV 导出模块。

路径安全策略：导出目录固定为仓库 run_data/scope_exports/；
文件名走白名单校验（仅字母/数字/下划线/点/连字符的 *.csv / *.json），
再经 resolve + containment 双重确认落在 EXPORT_DIR 内。
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

EXPORT_DIR = Path(__file__).resolve().parent / "run_data" / "scope_exports"

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*\.(csv|json)$")

# Windows 保留设备名（含带扩展名形式，如 NUL.csv 会被系统重定向到设备）。
_RESERVED_STEMS = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_export_path(filename: str) -> Path | None:
    """校验导出路径：白名单文件名、非保留名、规范化、必须落在 EXPORT_DIR 内。"""
    if not filename or not _SAFE_NAME_RE.match(filename):
        return None
    if filename.split(".")[0].upper() in _RESERVED_STEMS:
        return None
    base = EXPORT_DIR.resolve()
    base.mkdir(parents=True, exist_ok=True)
    candidate = (base / filename).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate


def dump_csv(filename: str, header: list[str], t: list[float], columns: list[list[float]]) -> Path | None:
    """把若干同长度数据列写成 CSV；返回写出的文件路径。

    内容先在内存中组好，再经 write_text 一次性写入校验过的路径。
    """
    path = safe_export_path(filename)
    if path is None:
        return None
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(["t_s"] + header)
    for i in range(len(t)):
        row = [f"{t[i]:.3f}"] + [f"{col[i]:.2f}" for col in columns]
        writer.writerow(row)
    # StringIO(newline="") 保留 csv.writer 的 \r\n；写入端不再做换行翻译。
    path.write_text(buf.getvalue(), encoding="utf-8-sig", newline="")
    return path


def save_layout_json(layout: dict) -> bool:
    """把界面布局（勾选/颜色/选项）写到固定路径，主线程外也可调用。"""
    import json
    path = safe_export_path("mmhand_scope_layout.json")
    if path is None:
        return False
    path.write_text(json.dumps(layout, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def load_layout_json() -> dict:
    """读取布局；不存在或损坏时返回空 dict。"""
    import json
    path = EXPORT_DIR / "mmhand_scope_layout.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_named_json(filename: str, obj) -> bool:
    """通用 JSON 存取（零位等小型状态），仍受白名单与目录限制。"""
    import json
    path = safe_export_path(filename)
    if path is None:
        return False
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def load_named_json(filename: str):
    """读取 JSON；不存在或损坏返回 None。"""
    import json
    path = EXPORT_DIR / filename
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
