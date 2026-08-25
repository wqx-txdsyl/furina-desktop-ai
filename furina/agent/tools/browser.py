"""浏览器工具（legacy-plan/5 §10-11）。

骨架：用系统默认浏览器打开 URL/搜索。后续可接浏览器自动化(Playwright)做点击/提取。
"""
from __future__ import annotations

import webbrowser
import urllib.parse
from typing import Any, Dict

from ..permission import Permission
from ..tool import BaseTool, ToolResult


class OpenUrlTool(BaseTool):
    name = "browser.open"
    description = "用系统浏览器打开一个网址"
    permission = Permission.L0_READ
    schema = {"type": "object", "properties": {"url": {"type": "string"}}}

    def run(self, url: str) -> ToolResult:
        href = url if "://" in url else "https://" + url
        try:
            webbrowser.open(href)
            return ToolResult(True, data={"opened": href}, verified=True, note=f"已打开 {href}")
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)


class SearchTool(BaseTool):
    name = "browser.search"
    description = "用默认搜索引擎搜索关键词"
    permission = Permission.L0_READ
    schema = {"type": "object", "properties": {"query": {"type": "string"}}}

    def run(self, query: str) -> ToolResult:
        href = "https://www.bing.com/search?q=" + urllib.parse.quote(query)
        try:
            webbrowser.open(href)
            return ToolResult(True, data={"opened": href}, verified=True, note=f"搜索：{query}")
        except Exception as e:
            return ToolResult(False, error=str(e), verified=False)
