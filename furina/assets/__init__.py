"""素材引擎：Manifest 模型 + 命名规范 + Resolver + Agnes 生成（plan/2）。"""
from .asset_manifest import (
    AssetEntry,
    AssetManifest,
    AssetResolver,
    naming_for,
    semantic_id_for,
)
from .agnes_client import AgnesClient, ImageGenerateOptions, ImageResult, VideoOptions

__all__ = [
    "AssetEntry",
    "AssetManifest",
    "AssetResolver",
    "naming_for",
    "semantic_id_for",
    "AgnesClient",
    "ImageGenerateOptions",
    "ImageResult",
    "VideoOptions",
]
