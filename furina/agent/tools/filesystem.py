"""文件系统工具（骨架为真实实现，权限在外层 enforcement）。

plan/5 §11 第一版优先：查找/打开/整理/重命名/创建文件夹。
分类启发式基于扩展名；真实归类策略可在 P7 细化。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List

from ..permission import Permission
from ..tool import BaseTool, ToolResult

_EXT_GROUP = {
    "pdf": "PDF",
    "image": ["jpg", "jpeg", "png", "gif", "webp", "bmp", "svg"],
    "zip": ["zip", "rar", "7z", "tar", "gz"],
    "doc": ["doc", "docx", "txt", "md", "ppt", "pptx", "xls", "xlsx"],
}

# 扩展名 → 目标文件夹名（与 planner 里 make_dirs 的目录名一致）
_GROUP_FOLDER = {"pdf": "PDF", "image": "Images", "zip": "ZIP", "doc": "Docs"}


def _resolve(path: str) -> Path:
    p = Path(os.path.expanduser(path)).resolve()
    return p


class ListDirTool(BaseTool):
    name = "fs.list_dir"
    description = "列出目录内容"
    permission = Permission.L0_READ
    schema = {"type": "object", "properties": {"path": {"type": "string"}}}

    def run(self, path: str = "~") -> ToolResult:
        p = _resolve(path)
        if not p.is_dir():
            return ToolResult(False, error=f"不是目录: {p}")
        items = []
        for it in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            items.append({"name": it.name, "is_dir": it.is_dir(), "size": it.stat().st_size if it.is_file() else 0})
        return ToolResult(True, data=items[:200], verified=True, note=f"目录 {p} 共 {len(items)} 项")


class MakeDirsTool(BaseTool):
    name = "fs.make_dirs"
    description = "在给定目录下创建多个文件夹"
    permission = Permission.L1_LOW_WRITE

    def run(self, base: str = "~", names: List[str] = None) -> ToolResult:
        names = names or []
        base_path = _resolve(base)
        for n in names:
            (base_path / n).mkdir(exist_ok=True)
        return ToolResult(True, data={"created": names},
                          verified=True, note=f"在 {base_path} 创建 {len(names)} 个目录")


class ReadFileTool(BaseTool):
    name = "fs.read_file"
    description = "读取一个文本文件的内容（前若干行）"
    permission = Permission.L0_READ
    schema = {"type": "object", "properties": {"path": {"type": "string"}, "max_lines": {"type": "integer"}}}

    def run(self, path: str, max_lines: int = 200) -> ToolResult:
        p = _resolve(path)
        if not p.is_file():
            return ToolResult(False, error=f"不是文件: {p}", verified=False)
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            return ToolResult(True, data={"path": str(p), "lines": lines[:max_lines]},
                              verified=True, note=f"{len(lines)} 行")
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)


class OrganizeTool(BaseTool):
    name = "fs.organize"
    description = "按扩展名把文件归类到子目录（用 make_dirs 已建的分组）"
    permission = Permission.L2_HIGH_RISK

    def run(self, base: str = "~", dry_run: bool = True) -> ToolResult:
        base_path = _resolve(base)
        moved = 0
        results = []
        for f in base_path.iterdir():
            if f.is_dir():
                continue
            group = self._group_for(f.suffix.lstrip(".").lower())
            if not group:
                continue
            target_dir = base_path / group
            if not target_dir.exists():
                continue
            if dry_run:
                results.append({"from": f.name, "to": group, "dry": True})
                continue
            dest = target_dir / f.name
            shutil.move(str(f), str(dest))
            moved += 1
            results.append({"from": f.name, "to": group})
        # Phase 13 终审 §10：verified 必须反映真实可观察结果
        #   - dry_run：预览本身就是真实结果（data 列出全部可归类项）
        #   - 真实移动：验证文件确实不在根目录（确实被移走）
        if dry_run:
            verified = True
        else:
            verified = all(not (base_path / r["from"]).exists() for r in results)
        return ToolResult(True, data=results, verified=verified,
                          note=f"dry_run={dry_run} 移动 {moved}")

    @staticmethod
    def _group_for(ext: str) -> str:
        for group, exts in _EXT_GROUP.items():
            if isinstance(exts, str):
                if ext == exts.lower():
                    return _GROUP_FOLDER[group]
            elif ext in exts:
                return _GROUP_FOLDER[group]
        return ""
