"""对话 CLI —— 演示 Furina Brain（M5）。

    python scripts/chat.py "我工作好久没休息了"
    环绕：加载状态(可传 --working / --idle) + 记忆，输出意图/情绪/台词/理由。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from furina.config import load_config, LLMProfile
from furina.llm import get_adapter
from furina.brain import FurinaBrain
from furina.state import CharacterState, MacroState
from furina.memory import MemoryStore, MemoryEngine


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="*", help="用户说的话")
    ap.add_argument("--working", action="store_true", help="模拟用户在工作")
    ap.add_argument("--idle", action="store_true", help="模拟用户空闲")
    args = ap.parse_args()

    cfg = load_config()
    if not cfg.zhipu_api_key:
        print("缺少 ZHIPU_API_KEY")
        return 1
    llm = get_adapter("zhipu")(LLMProfile(api_key=cfg.zhipu_api_key))
    store = MemoryStore(cfg.db_path)
    from furina.core import EventBus
    mem = MemoryEngine(EventBus(), store)
    brain = FurinaBrain(llm, mem)

    state = CharacterState()
    state.life.macro = MacroState.WORKING if args.working else MacroState.IDLE
    state.user_working = args.working
    state.user_idle_seconds = 0 if args.working else 120

    text = " ".join(args.text) or "今天过得怎么样？"
    out = brain.think(state=state, user_text=text)
    print(f"[意图] {out.intent}   [情绪] {out.emotion}   优先级 {out.priority:.2f}")
    print(f"[芙宁娜] {out.speech}")
    print(f"[理由] {out.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
