"""内置工具集。

既有 + Phase 14D/E/G 扩展：
- fs.* primitives（exists/stat/search/create_file/write_text/append_text/replace_text/
  copy/move/rename/create_dir/open_path/delete）
- doc.* / docx.create / pptx.create / xlsx.create（TXT/MD + Office reopen-verify）
- desktop.active_window / desktop.list_windows（只读 L0）
- app.launch（经 ApplicationCatalog 解析真实 target）
"""
from .filesystem import (
    AppendTextTool, CopyTool, CreateDirTool, CreateFileTool, DeleteTool, ExistsTool,
    ListDirTool, MakeDirsTool, MoveTool, OpenPathTool, OrganizeTool, ReadFileTool,
    RenameTool, ReplaceTextTool, SearchTool, StatTool, WriteTextTool,
)
from .apps import LaunchTool
from .browser import OpenUrlTool, SearchTool as BrowserSearchTool
from .computer import ScreenshotTool
from .desktop import ActiveWindowTool, ListWindowsTool
from furina.agent.capabilities.documents import (
    DocAppendTool, DocCreateTool, DocEditTool, DocReadTool, DocWriteTool,
    DocxCreateTool, PptxCreateTool, XlsxCreateTool,
)

ALL_TOOLS = [
    # fs（旧）
    ListDirTool, MakeDirsTool, OrganizeTool, ReadFileTool,
    # fs（Phase 14D）
    ExistsTool, StatTool, SearchTool, CreateFileTool, WriteTextTool, AppendTextTool,
    ReplaceTextTool, CopyTool, MoveTool, RenameTool, CreateDirTool, OpenPathTool, DeleteTool,
    # apps / browser / computer / desktop
    LaunchTool, OpenUrlTool, BrowserSearchTool, ScreenshotTool,
    ActiveWindowTool, ListWindowsTool,
    # documents（Phase 14E）
    DocCreateTool, DocReadTool, DocWriteTool, DocAppendTool, DocEditTool,
    DocxCreateTool, PptxCreateTool, XlsxCreateTool,
]

__all__ = ["ALL_TOOLS"]
