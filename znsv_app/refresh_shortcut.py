"""重指桌面快捷方式图标并刷新 Explorer 图标缓存。

用途：appicon.ico 内容更换后，Windows 可能仍显示旧缓存；本脚本复制一份新文件名
appicon_c.ico（不同路径绕过缓存）、把快捷方式指向它并调用 ie4uinit 刷新。

运行：.venv\\Scripts\\python znsv_app/refresh_shortcut.py
（2026-10-28 随工程搬运；注意运行它会把桌面「ZNSV Studio」快捷方式指到本副本。）
"""
import base64
import shutil
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parents[1]
PYTHONW = ROOT / '.venv' / 'Scripts' / 'pythonw.exe'
MAIN = APP_DIR / 'main.py'


def main():
    source = APP_DIR / 'appicon.ico'
    ico = APP_DIR / 'appicon_c.ico'
    if not source.exists():
        sys.exit(f'缺少 {source}；先运行 icon_design.py 生成。')
    shutil.copyfile(source, ico)  # 新文件名绕过 Explorer 图标缓存
    ps = "\n".join([
        '$desktop = [Environment]::GetFolderPath(\'Desktop\')',
        '$ws = New-Object -ComObject WScript.Shell',
        "$path = Join-Path $desktop 'ZNSV Studio.lnk'",
        '$lnk = $ws.CreateShortcut($path)',
        f"$lnk.TargetPath = '{PYTHONW}'",
        f"$lnk.Arguments = '\"{MAIN}\"'",
        f"$lnk.WorkingDirectory = '{APP_DIR}'",
        f"$lnk.IconLocation = '{ico},0'",
        "$lnk.Description = 'ZNSV Studio - 8ch transmitter UI'",
        '$lnk.Save()',
        'Write-Output (\'ICON=\' + $lnk.IconLocation)',
        'Start-Process ie4uinit.exe -ArgumentList \'-show\' -WindowStyle Hidden',
        'Write-Output \'CACHE_REFRESHED\'',
    ])
    encoded = base64.b64encode(ps.encode('utf-16-le')).decode()
    result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                             '-EncodedCommand', encoded],
                            capture_output=True, encoding='gbk', errors='replace')
    print(result.stdout.strip())
    if result.returncode != 0 or 'CACHE_REFRESHED' not in result.stdout:
        print('stderr:', result.stderr.strip()[:300])
        sys.exit(1)


if __name__ == '__main__':
    main()
