"""统一异常类型。"""
from __future__ import annotations


class FurinaError(Exception):
    """基类。"""


class ConfigError(FurinaError):
    """配置缺失 / 非法。"""


class LLMError(FurinaError):
    """LLM 调用失败。"""


class AssetError(FurinaError):
    """素材缺失 / 解析失败。"""


class AgentError(FurinaError):
    """Agent 工具执行失败。"""


class DirectorConflictError(FurinaError):
    """Director 仲裁冲突（本应不可达，出现说明某模块越权直接调用）。"""
