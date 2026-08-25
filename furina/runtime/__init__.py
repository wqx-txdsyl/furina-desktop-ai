"""Runtime 包：把一切真正运行在 Windows 桌面上（legacy-plan/7）。"""
from .world import DesktopWorld, Surface, Vec2
from .asset_manager import AssetManager
from .furina_window import FurinaWindow
from .input_router import InputRouter
from .window_awareness import WindowInfo, WindowAwareness
from .frame import CharacterRuntimeFrame, SCHEMA_VERSION
from .frame_builder import RuntimeFrameBuilder
from .renderer_adapter import renderer_adapter

__all__ = [
    "DesktopWorld",
    "Surface",
    "Vec2",
    "AssetManager",
    "FurinaWindow",
    "InputRouter",
    "WindowInfo",
    "WindowAwareness",
    "CharacterRuntimeFrame",
    "SCHEMA_VERSION",
    "RuntimeFrameBuilder",
    "renderer_adapter",
]
