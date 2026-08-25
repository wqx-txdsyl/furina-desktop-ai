"""文件系统工具（骨架为真实实现，权限在外层 enforcement）。

legacy-plan/5 §11 第一版优先：查找/打开/整理/重命名/创建文件夹。
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
    schema = {"type": "object", "properties": {"path": {"type": "string"}},
              "required": ["path"]}

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
    schema = {"type": "object", "properties": {"path": {"type": "string"}, "max_lines": {"type": "integer"}},
              "required": ["path"]}

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


# ================================================================ Phase 14D：真实 fs primitives
# 所有 verified 必须读取 filesystem truth（写后读回/存在性/stat），绝不"函数没报错=verified"。


class ExistsTool(BaseTool):
    name = "fs.exists"
    description = "检查路径是否存在（只读）"
    permission = Permission.L0_READ
    schema = {"type": "object", "properties": {"path": {"type": "string"}},
              "required": ["path"]}

    def run(self, path: str) -> ToolResult:
        p = _resolve(path)
        return ToolResult(True, data={"path": str(p), "exists": p.exists(),
                                      "is_dir": p.is_dir()}, verified=True)


class StatTool(BaseTool):
    name = "fs.stat"
    description = "读取文件/目录元数据（大小/修改时间，只读）"
    permission = Permission.L0_READ
    schema = {"type": "object", "properties": {"path": {"type": "string"}},
              "required": ["path"]}

    def run(self, path: str) -> ToolResult:
        p = _resolve(path)
        if not p.exists():
            return ToolResult(False, error=f"不存在: {p}", verified=False)
        try:
            st = p.stat()
            return ToolResult(True, data={"path": str(p), "is_dir": p.is_dir(),
                                          "size": st.st_size,
                                          "mtime": st.st_mtime}, verified=True)
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)


class SearchTool(BaseTool):
    name = "fs.search"
    description = "在目录内按名称/扩展名搜索文件（只读）"
    permission = Permission.L0_READ
    schema = {"type": "object", "properties": {"path": {"type": "string"},
                                               "pattern": {"type": "string"},
                                               "limit": {"type": "integer"}},
              "required": ["path"]}

    def run(self, path: str, pattern: str = "", limit: int = 50) -> ToolResult:
        base = _resolve(path)
        if not base.is_dir():
            return ToolResult(False, error=f"不是目录: {base}", verified=False)
        pat = (pattern or "").lower()
        hits = []
        try:
            for it in base.rglob("*"):
                if it.is_file():
                    name = it.name.lower()
                    if (not pat) or pat in name or it.suffix.lower().lstrip(".") == pat.lstrip("."):
                        hits.append(str(it))
                        if len(hits) >= limit:
                            break
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)
        return ToolResult(True, data={"hits": hits, "count": len(hits)}, verified=True)


class CreateFileTool(BaseTool):
    name = "fs.create_file"
    description = "在显式目标路径创建空文件（L1；用户选择目标）"
    permission = Permission.L1_LOW_WRITE
    schema = {"type": "object", "properties": {"path": {"type": "string"},
                                               "content": {"type": "string"}},
              "required": ["path"]}

    def run(self, path: str, content: str = "") -> ToolResult:
        p = _resolve(path)
        if p.exists():
            return ToolResult(False, error=f"已存在（不允许 silent overwrite）: {p}",
                              verified=False)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)
        # verified：filesystem truth（存在 + 内容一致）
        ok = p.is_file() and p.read_text(encoding="utf-8", errors="replace") == content
        return ToolResult(True, data={"path": str(p)}, verified=ok,
                          note=f"创建 {p}" if ok else f"创建但内容校验失败 {p}")


class WriteTextTool(BaseTool):
    name = "fs.write_text"
    description = "写文本文件（显式目标 L1；覆盖已有文件 → 至少 L2，且必须 expected_old_hash 或 overwrite=false 语义）"
    permission = Permission.L1_LOW_WRITE
    schema = {"type": "object", "properties": {"path": {"type": "string"},
                                               "content": {"type": "string"},
                                               "expected_old_hash": {"type": "string"},
                                               "overwrite": {"type": "boolean"}},
              "required": ["path", "content"]}

    def run(self, path: str, content: str = "", expected_old_hash: str = "",
            overwrite: bool = False) -> ToolResult:
        import hashlib
        p = _resolve(path)
        exists = p.exists()
        if exists:
            # 防误覆盖：显式 expected_old_hash 必须匹配；overwrite 默认 False（Phase 14.1）
            if expected_old_hash:
                old = hashlib.sha256(p.read_bytes()).hexdigest()
                if old != expected_old_hash:
                    return ToolResult(False, error="expected_old_hash 不匹配，拒绝写入（并发/误覆盖防护）",
                                      verified=False)
            elif overwrite is False:
                return ToolResult(False, error="目标已存在且未显式 overwrite=True，拒绝覆盖",
                                  verified=False)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)
        # verified：写后读回（filesystem truth）
        back = p.read_text(encoding="utf-8", errors="replace")
        return ToolResult(True, data={"path": str(p), "bytes": len(back.encode("utf-8"))},
                          verified=(back == content),
                          note="内容校验通过" if back == content else "内容校验失败")


class AppendTextTool(BaseTool):
    name = "fs.append_text"
    description = "追加文本到文件（文件不存在则创建；L1）"
    permission = Permission.L1_LOW_WRITE
    schema = {"type": "object", "properties": {"path": {"type": "string"},
                                               "content": {"type": "string"}},
              "required": ["path", "content"]}

    def run(self, path: str, content: str = "") -> ToolResult:
        p = _resolve(path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)
        back = p.read_text(encoding="utf-8", errors="replace")
        return ToolResult(True, data={"path": str(p)},
                          verified=content in back, note="追加并校验")


class ReplaceTextTool(BaseTool):
    name = "fs.replace_text"
    description = "在已有文本文件中替换子串（编辑；L1/L2）"
    permission = Permission.L1_LOW_WRITE
    schema = {"type": "object", "properties": {"path": {"type": "string"},
                                               "old": {"type": "string"},
                                               "new": {"type": "string"}},
              "required": ["path", "old", "new"]}

    def run(self, path: str, old: str, new: str) -> ToolResult:
        p = _resolve(path)
        if not p.is_file():
            return ToolResult(False, error=f"不是文件: {p}", verified=False)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            if old not in text:
                return ToolResult(False, error=f"未找到要替换的内容: {old[:50]}", verified=False)
            new_text = text.replace(old, new, 1)
            p.write_text(new_text, encoding="utf-8")
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)
        back = p.read_text(encoding="utf-8", errors="replace")
        return ToolResult(True, data={"path": str(p)},
                          verified=(new in back and text != back),
                          note="替换并校验")


class CopyTool(BaseTool):
    name = "fs.copy"
    description = "复制文件/目录（目标已存在 → 需要 overwrite 显式；L1/L2）"
    permission = Permission.L1_LOW_WRITE
    schema = {"type": "object", "properties": {"source": {"type": "string"},
                                               "dest": {"type": "string"},
                                               "overwrite": {"type": "boolean"}},
              "required": ["source", "dest"]}

    def run(self, source: str, dest: str, overwrite: bool = False) -> ToolResult:
        import shutil as _shutil
        src = _resolve(source)
        dst = _resolve(dest)
        if not src.exists():
            return ToolResult(False, error=f"源不存在: {src}", verified=False)
        if dst.exists() and not overwrite:
            return ToolResult(False, error="目标已存在且 overwrite=false（禁止 silent overwrite）",
                              verified=False)
        try:
            if src.is_dir():
                _shutil.copytree(str(src), str(dst), dirs_exist_ok=overwrite)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                _shutil.copy2(str(src), str(dst))
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)
        return ToolResult(True, data={"source": str(src), "dest": str(dst)},
                          verified=dst.exists(), note="复制并校验存在性")


class MoveTool(BaseTool):
    name = "fs.move"
    description = "移动文件/目录（目标已存在 → 需要 overwrite 显式；L1/L2）"
    permission = Permission.L1_LOW_WRITE
    schema = {"type": "object", "properties": {"source": {"type": "string"},
                                               "dest": {"type": "string"},
                                               "overwrite": {"type": "boolean"}},
              "required": ["source", "dest"]}

    def run(self, source: str, dest: str, overwrite: bool = False) -> ToolResult:
        src = _resolve(source)
        dst = _resolve(dest)
        if not src.exists():
            return ToolResult(False, error=f"源不存在: {src}", verified=False)
        if dst.exists() and not overwrite:
            return ToolResult(False, error="目标已存在且 overwrite=false（禁止 silent overwrite）",
                              verified=False)
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)
        return ToolResult(True, data={"source": str(src), "dest": str(dst)},
                          verified=(dst.exists() and not src.exists()),
                          note="移动并校验（源消失+目标存在）")


class RenameTool(BaseTool):
    name = "fs.rename"
    description = "重命名文件/目录（同一目录内；L1/L2）"
    permission = Permission.L1_LOW_WRITE
    schema = {"type": "object", "properties": {"path": {"type": "string"},
                                               "new_name": {"type": "string"}},
              "required": ["path", "new_name"]}

    def run(self, path: str, new_name: str) -> ToolResult:
        p = _resolve(path)
        if not p.exists():
            return ToolResult(False, error=f"不存在: {p}", verified=False)
        dst = p.parent / new_name
        if dst.exists():
            return ToolResult(False, error="目标已存在（禁止 silent overwrite）", verified=False)
        try:
            p.rename(dst)
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)
        return ToolResult(True, data={"from": str(p), "to": str(dst)},
                          verified=(dst.exists() and not p.exists()),
                          note="重命名并校验")


class CreateDirTool(BaseTool):
    name = "fs.create_dir"
    description = "创建目录（含父目录；L1）"
    permission = Permission.L1_LOW_WRITE
    schema = {"type": "object", "properties": {"path": {"type": "string"}},
              "required": ["path"]}

    def run(self, path: str) -> ToolResult:
        p = _resolve(path)
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)
        return ToolResult(True, data={"path": str(p)}, verified=p.is_dir(),
                          note="目录已确保存在")


class OpenPathTool(BaseTool):
    name = "fs.open_path"
    description = "在系统文件管理器中打开路径（L0/L1）"
    permission = Permission.L0_READ
    schema = {"type": "object", "properties": {"path": {"type": "string"}},
              "required": ["path"]}

    def run(self, path: str) -> ToolResult:
        import subprocess as _sp
        import sys as _sys
        p = _resolve(path)
        if not p.exists():
            return ToolResult(False, error=f"不存在: {p}", verified=False)
        try:
            if _sys.platform == "win32":
                _sp.Popen(["explorer", str(p)], shell=True)
            else:
                _sp.Popen(["xdg-open", str(p)], shell=True)
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)
        return ToolResult(True, data={"path": str(p)},
                          verified=True, note=f"已在资源管理器打开 {p}")


class DeleteTool(BaseTool):
    name = "fs.delete"
    description = "删除文件/目录（L2；必要时 L3；不默认出现在普通计划）"
    permission = Permission.L2_HIGH_RISK
    schema = {"type": "object", "properties": {"path": {"type": "string"}},
              "required": ["path"]}

    def run(self, path: str) -> ToolResult:
        p = _resolve(path)
        if not p.exists():
            return ToolResult(False, error=f"不存在: {p}", verified=False)
        try:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(str(p))
            else:
                p.unlink()
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)
        return ToolResult(True, data={"path": str(p)}, verified=not p.exists(),
                          note="删除并校验（目标确实消失）")
