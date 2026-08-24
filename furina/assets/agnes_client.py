"""Agnes AI 客户端 —— 资产生成（plan/2 §十 素材生成管线）。

基于教程：
- gen_img_course.md → agnes-image-2.1-flash（文生图 / 图生图 / 多图合成）
- gen_gif_course.md  → agnes-video-v2.0（文生视频 / 图生视频 / 关键帧）

当前价格 $0，可先低成本批量生成素材。
"""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from furina.core import get_logger

log = get_logger("assets.agnes")

IMAGE_ENDPOINT = "https://apihub.agnes-ai.com/v1/images/generations"
VIDEO_ENDPOINT = "https://apihub.agnes-ai.com/v1/videos"
VIDEO_QUERY = "https://apihub.agnes-ai.com/agnesapi"
IMAGE_MODEL = "agnes-image-2.1-flash"
VIDEO_MODEL = "agnes-video-v2.0"


# ---------------------------------------------------------------- 图片
@dataclass
class ImageGenerateOptions:
    prompt: str
    size: str = "1K"           # 1K/2K/3K/4K
    ratio: str = "1:1"         # 1:1/3:4/4:3/16:9/9:16/2:3/3:2/21:9
    image: List[str] = field(default_factory=list)  # 图生图/多图：url 或 data uri
    return_base64: bool = False
    seed: Optional[int] = None


@dataclass
class ImageResult:
    url: Optional[str] = None
    b64: Optional[str] = None
    revised_prompt: Optional[str] = None


@dataclass
class VideoOptions:
    prompt: str
    image: Optional[str] = None                 # 图生视频 url
    keyframes: List[str] = field(default_factory=list)  # 关键帧 url 数组
    width: int = 1152
    height: int = 768
    num_frames: int = 121                        # ≤441, 8n+1
    frame_rate: int = 24
    seed: Optional[int] = None
    negative_prompt: Optional[str] = None


class AgnesClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._http = httpx.Client(timeout=360.0)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def is_available(self) -> bool:
        return bool(self.api_key)

    # -------------------------------------------------- 图片
    def generate_image(self, opts: ImageGenerateOptions) -> ImageResult:
        payload: Dict[str, Any] = {
            "model": IMAGE_MODEL,
            "prompt": opts.prompt,
            "size": opts.size,
            "extra_body": {},
        }
        if opts.ratio:
            payload["ratio"] = opts.ratio
        if opts.seed is not None:
            payload["seed"] = opts.seed
        if opts.image:
            payload["extra_body"]["image"] = _as_data_uris(opts.image)
        # 响应格式：base64 或 url
        payload["extra_body"]["response_format"] = "b64_json" if opts.return_base64 else "url"
        r = self._http.post(IMAGE_ENDPOINT, headers=self._headers(), json=payload)
        r.raise_for_status()
        d = r.json()
        item = d["data"][0]
        return ImageResult(
            url=item.get("url"),
            b64=item.get("b64_json"),
            revised_prompt=item.get("revised_prompt"),
        )

    # -------------------------------------------------- 视频
    def create_video(self, opts: VideoOptions) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": VIDEO_MODEL,
            "prompt": opts.prompt,
            "height": opts.height,
            "width": opts.width,
            "num_frames": opts.num_frames,
            "frame_rate": opts.frame_rate,
        }
        if opts.image:
            payload["image"] = opts.image
        if opts.keyframes:
            payload["extra_body"] = {"image": opts.keyframes, "mode": "keyframes"}
        if opts.seed is not None:
            payload["seed"] = opts.seed
        if opts.negative_prompt:
            payload["negative_prompt"] = opts.negative_prompt
        for attempt in range(6):
            r = self._http.post(VIDEO_ENDPOINT, headers=self._headers(), json=payload)
            if r.status_code in (429, 503):
                time.sleep(2.0 * (attempt + 1))   # 退避重试，处理视频接口限流
                continue
            r.raise_for_status()
            return r.json()
        r = self._http.post(VIDEO_ENDPOINT, headers=self._headers(), json=payload)
        r.raise_for_status()
        return r.json()

    def get_video_result(self, video_id: str, model_name: Optional[str] = None,
                         retries: int = 6, backoff: float = 2.0) -> Dict[str, Any]:
        params = {"video_id": video_id}
        if model_name:
            params["model_name"] = model_name
        for attempt in range(retries):
            try:
                r = self._http.get(VIDEO_QUERY, headers=self._headers(), params=params)
            except httpx.HTTPError as e:
                raise
            if r.status_code in (429, 503):
                time.sleep(backoff * (attempt + 1))   # 退避重试，处理限流
                continue
            r.raise_for_status()
            return r.json()
        r = self._http.get(VIDEO_QUERY, headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json()

    def wait_video(self, video_id: str, timeout: float = 600.0, interval: float = 5.0) -> Dict[str, Any]:
        """轮询到 completed / failed（视频是异步任务）。"""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            d = self.get_video_result(video_id)
            st = d.get("status")
            if st in ("completed", "failed"):
                return d
            time.sleep(interval)
        raise TimeoutError(f"视频 {video_id} 生成超时")

    @staticmethod
    def video_url_from(result: Dict[str, Any]) -> Optional[str]:
        """取视频下载地址：实际响应里 `url` 在**顶层**（metadata 可能为 null），文档写 metadata.url。

        两者都兼容，避免漏拿片源导致多帧动画卡死。
        """
        u = result.get("url")
        if u:
            return u
        meta = result.get("metadata")
        if isinstance(meta, dict):
            return meta.get("url")
        return None


# ---------------------------------------------------------------- helpers
def _as_data_uris(paths: List[str]) -> List[str]:
    """把本地路径转成 data:image/png;base64 形式（Agnes 支持 Data URI）。"""
    out: List[str] = []
    for p in paths:
        if p.startswith("data:") or p.startswith("http"):
            out.append(p)
        else:
            data = Path(p).read_bytes()
            b64 = base64.b64encode(data).decode()
            out.append(f"data:image/png;base64,{b64}")
    return out
