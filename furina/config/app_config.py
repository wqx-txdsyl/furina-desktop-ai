"""应用配置。

从项目根目录读取 ``.env``（ZHIPU_API_KEY / AGNES_API_KEY），
并集中管理可拔插的 LLM 与资产生成配置。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv as _load_dotenv
except Exception:  # pragma: no cover - python-dotenv 可缺省
    _load_dotenv = None  # type: ignore[assignment]


# ---------------------------------------------------------------- LLM 配置
@dataclass(frozen=True)
class LLMProfile:
    """一个可拔插的 LLM 配置档。

    - ``model`` 决定使用哪个智谱 GLM 模型。
    - 默认为 ``glm-4v-flash``：智谱免费、原生支持「视觉 + 对话」的模型，
      可用于屏幕感知 / 素材质检 / 对话推理。
    - 需要更强纯文本推理时可在 .env 里切换到 ``glm-4.5-air`` 等。
    """

    provider: str = "zhipu"              # 预留多 provider 扩展
    model: str = "glm-4v-flash"
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    api_key: str = ""
    temperature: float = 0.7
    max_tokens: int = 1024          # glm-4v-flash 上限 1024；其它模型可调
    timeout: float = 120.0          # B1：单次 LLM 调用的有界超时（connect/read/write；直接对话不得无限 WAIT）
    supports_vision: bool = True
    supports_dialogue: bool = True


@dataclass
class AppConfig:
    """聚合后的应用配置。"""

    root_dir: Path
    # 键
    zhipu_api_key: str = ""
    agnes_api_key: str = ""
    # 模型
    llm: LLMProfile = field(default_factory=LLMProfile)
    # 调试
    debug: bool = False
    # R1.1-3：直接对话回合的总体验预算（用户可见：从入队到 terminal 的整回合上限，
    # attempt+retry 共享同一 deadline）。独立于 LLM transport timeout（LifeBrain/Agent 不变）。
    direct_turn_timeout: float = 30.0
    # 素材 / 数据目录
    assets_dir: Path = field(default_factory=Path)
    data_dir: Path = field(default_factory=Path)
    # Phase 15 D4：用户本地时区（IANA 名）。空 = 未配置 → 时间语义 fail-closed
    # （不解析相对日期，绝不静默猜测某个日历）—— 唯一的显式时区权威来源。
    timezone: str = ""

    @property
    def models_dir(self) -> Path:
        """机器可读的素材 manifest / 生成产物目录。"""
        return self.data_dir / "assets"

    @property
    def model_manifest_path(self) -> Path:
        return self.models_dir / "manifest.json"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "furina.db"

    @property
    def memory_archive_dir(self) -> Path:
        return self.data_dir / "memory"


def _resolve_root() -> Path:
    """定位项目根目录。

    - 源码运行：furina/config/app_config.py → parents[2] = 项目根。
    - PyInstaller 冻结：资源在 sys._MEIPASS（onefile 解包），数据在可执行文件旁的数据目录。
    允许 FURINA_ROOT 覆盖。
    """
    import sys as _sys
    env_root = os.environ.get("FURINA_ROOT")
    if env_root:
        return Path(env_root).resolve()
    # 冻结（frozen）时：已打包的数据放在可执行文件旁。开发时 _MEIPASS 存在但用源码树。
    if getattr(_sys, "_MEIPASS", None) and _sys.frozen:
        exe_dir = Path(_sys.executable).resolve().parent
        return exe_dir
    here = Path(__file__).resolve()
    return here.parents[2]


def load_config(env_path: Optional[Path] = None) -> AppConfig:
    """读取 .env 并构建 AppConfig。

    未找到 .env 时回退到环境变量，保证缺省也可启动骨架。
    """
    root = _resolve_root()
    if _load_dotenv is not None:
        _load_dotenv(env_path or (root / ".env"), override=False)

    cfg = AppConfig(
        root_dir=root,
        zhipu_api_key=os.environ.get("ZHIPU_API_KEY", ""),
        agnes_api_key=os.environ.get("AGNES_API_KEY", ""),
        debug=os.environ.get("FURINA_DEBUG", "").lower() in {"1", "true", "yes"},
        # Phase 15 D4/R1：显式用户时区（IANA 名，如 FURINA_TIMEZONE=Asia/Shanghai）。
        # 空 = 未配置 → 时间语义 fail-closed；不猜测、不做固定偏移兜底。
        timezone=os.environ.get("FURINA_TIMEZONE", ""),
        assets_dir=root / "data" / "assets",
        data_dir=root / "data",
    )
    # 允许 .env 覆盖模型档（拔插）：可在 .env 里换 provider/base_url/model/key，实现“换更快的模型”。
    provider = os.environ.get("FURINA_LLM_PROVIDER", "zhipu")
    model = os.environ.get("FURINA_LLM_MODEL")
    base_url = os.environ.get("FURINA_LLM_BASE_URL")
    env_key = os.environ.get("FURINA_LLM_API_KEY", cfg.zhipu_api_key)
    if provider != "zhipu" or model or base_url:
        llm = LLMProfile(provider=provider, model=model or cfg.llm.model,
                         base_url=base_url or cfg.llm.base_url,
                         api_key=env_key)
        # 换到 openai_compat 时仍允许指定模型
        if provider == "openai_compat":
            llm = LLMProfile(provider="openai_compat", model=model or "deepseek-chat",
                             base_url=base_url or "https://api.deepseek.com/v1",
                             api_key=env_key)
        cfg.llm = llm
    return cfg
