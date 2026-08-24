"""Phase 13 —— Functional Runtime Harness 入口（等价 `python main.py --harness`）。

用法：python scripts/runtime_harness.py
"""
from __future__ import annotations

import sys

from furina.app import run_harness

if __name__ == "__main__":
    run_harness()
