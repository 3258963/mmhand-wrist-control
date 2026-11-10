"""ZNSV Studio 独立入口；可从任意工作目录启动，不自动连接硬件。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from znsv_app.window import run

if __name__ == '__main__':
    sys.exit(run())
