"""内置工具集。"""
from .filesystem import ListDirTool, MakeDirsTool, OrganizeTool, ReadFileTool
from .apps import LaunchTool
from .browser import OpenUrlTool, SearchTool
from .computer import ScreenshotTool

ALL_TOOLS = [ListDirTool, MakeDirsTool, OrganizeTool, ReadFileTool, LaunchTool, OpenUrlTool, SearchTool,
             ScreenshotTool]

__all__ = ["ALL_TOOLS", "ListDirTool", "MakeDirsTool", "OrganizeTool", "ReadFileTool",
           "LaunchTool", "OpenUrlTool", "SearchTool", "ScreenshotTool"]
