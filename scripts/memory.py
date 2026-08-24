"""记忆 CLI —— 查看/添加/夜间巩固（plan/6 §32, §40）。

    python scripts/memory.py list          # 列出记忆
    python scripts/memory.py add "用户让我整理下载文件" --importance 0.9 --level episodic
    python scripts/memory.py consolidate   # 夜间巩固（把近期事件概括为一条总结记忆）
    python scripts/memory.py relationship  # 查看关系维度
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from furina.config import load_config
from furina.memory import MemoryStore, MemoryEngine, MemoryLevel, MemorySource
from furina.core import EventBus


def main() -> int:
    cfg = load_config()
    store = MemoryStore(cfg.db_path)
    mem = MemoryEngine(EventBus(), store)
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("relationship")
    p_add = sub.add_parser("add")
    p_add.add_argument("text")
    p_add.add_argument("--importance", type=float, default=0.7)
    p_add.add_argument("--level", default="episodic")
    sub.add_parser("consolidate")
    args = ap.parse_args()

    if args.cmd == "list":
        rows = mem.store.query(limit=30)
        if not rows:
            print("（暂无记忆）")
        for m in rows:
            print(f"[{m.level.value}/{m.source.value}] imp={m.importance:.2f} conf={m.confidence:.2f} :: {m.content}")
    elif args.cmd == "add":
        m = mem.observe(args.text, level=MemoryLevel(args.level), importance=args.importance,
                        source=MemorySource.USER_EXPLICIT)
        print("已记录" if m else "未达形成阈值，未记录")
    elif args.cmd == "consolidate":
        recent = mem.store.query(limit=20)
        summ = mem.nightly_consolidate(recent)
        print(f"巩固 -> {summ.content[:80]}")
    elif args.cmd == "relationship":
        print(mem.relationship.as_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
