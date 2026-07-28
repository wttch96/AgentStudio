"""集中管理环境配置，并对危险监听地址进行前置校验。"""

from __future__ import annotations

import os
import logging
from logging import Logger
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
# WORKSPACE_ROOT 由 Settings.workspace_root 覆盖，默认是 BACKEND_ROOT.parent。
WORKSPACE_ROOT = BACKEND_ROOT.parent

WORKSPACE_NAME = ".workspace"


@dataclass(frozen=True, slots=True)
class Settings:
    """后端运行配置。

    API Key 只保存在进程环境中，任何 API 响应都只返回“是否已配置”。
    """

    backend_host: str = "127.0.0.1"
    backend_port: int = 5000
    frontend_port: int = 5173
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"
    # 仅用于本地费用估算，单位为美元 / 百万 token；价格变化时可通过 .env 覆盖。
    deepseek_cache_hit_price: float = 0.0028
    deepseek_cache_miss_price: float = 0.14
    deepseek_output_price: float = 0.28
    anthropic_api_key: str = ""
    anthropic_auth_token: str = ""
    anthropic_base_url: str = ""
    claude_model: str = "claude-sonnet-4-5"
    max_concurrent_agents: int = 5
    agent_max_turns: int = 20
    agent_timeout_seconds: int = 1200
    # ── 迭代与停止条件 ──
    max_graph_iterations: int = 30
    max_replan_iterations: int = 5
    max_task_revisions: int = 2
    # 可以被覆盖，默认是 WORKSPACE_ROOT，backend的父目录。
    workspace_root: Path = WORKSPACE_ROOT
    # 显式覆盖对测试和嵌入式部署很有用。运行时安装通常不设置它，以便存储跟随 `current-project.yaml`。
    instance_dir: Path | None = None

    _logger: Logger = logging.getLogger(__name__)

    @property
    def data_dir(self) -> Path:
        """数据库存放目录。

        数据库跟随当前项目，保存在 .workspace/<current-project>/db/ 下。
        从 current-project.yaml 读取当前项目名；
        """
        if self.instance_dir is not None:
            return Path(self.instance_dir)
        current = self._read_current_project()
        if current:
            return self.workspace_root / WORKSPACE_NAME / current / "db"
        return self.workspace_root / WORKSPACE_NAME / ".system" / "db"

    def _read_current_project(self) -> str:
        """从 .workspace/current-project.yaml 读取当前项目名称。"""
        yaml_path = self.workspace_root / WORKSPACE_NAME / "current-project.yaml"
        if not yaml_path.is_file():
            return ""
        try:
            import yaml
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            return str(data.get("project_id", "")).strip()
        except Exception:
            return ""

    @property
    def project_data_dir(self) -> Path:
        """当前项目的数据目录, 一般在 .workspace/<current-project>/ 下。"""
        if self.instance_dir is not None:
            return Path(self.instance_dir)
        current = self._read_current_project()
        if current:
            return self.workspace_root / ".workspace" / current
        return self.workspace_root / ".workspace" / ".system"

    @property
    def database_path(self) -> Path:
        """SQLite is reserved for the RAG full-text/vector index only."""
        return self.project_data_dir / "db" / "rag.db"

    @property
    def runtime_dir(self) -> Path:
        """Runtime records live directly below the current project directory."""
        return self.project_data_dir

    @property
    def demo_mode(self) -> bool:
        return not (self.deepseek_api_key and self.claude_configured)

    @property
    def claude_configured(self) -> bool:
        """直连 API Key 或 CC Switch 管理 token 任一存在即可运行 Claude Agent。"""

        return bool(self.anthropic_api_key or self.anthropic_auth_token)

    @property
    def claude_route(self) -> str:
        if not self.anthropic_base_url:
            return "direct"
        if self.anthropic_base_url.rstrip("/") in {
            "http://127.0.0.1:15721",
            "http://localhost:15721",
        }:
            return "cc-switch"
        return "custom"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(WORKSPACE_ROOT / ".env")
        host = os.getenv("BACKEND_HOST", "127.0.0.1")
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("BACKEND_HOST 必须是回环地址，当前项目禁止对外网卡监听。")

        return cls(
            backend_host=host,
            backend_port=int(os.getenv("BACKEND_PORT", "5000")),
            frontend_port=int(os.getenv("FRONTEND_PORT", "5173")),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
            deepseek_cache_hit_price=float(
                os.getenv("DEEPSEEK_CACHE_HIT_PRICE_USD_PER_MILLION", "0.0028")
            ),
            deepseek_cache_miss_price=float(
                os.getenv("DEEPSEEK_CACHE_MISS_PRICE_USD_PER_MILLION", "0.14")
            ),
            deepseek_output_price=float(
                os.getenv("DEEPSEEK_OUTPUT_PRICE_USD_PER_MILLION", "0.28")
            ),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            anthropic_auth_token=os.getenv("ANTHROPIC_AUTH_TOKEN", ""),
            anthropic_base_url=os.getenv("ANTHROPIC_BASE_URL", ""),
            claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5"),
            max_concurrent_agents=max(1, int(os.getenv("MAX_CONCURRENT_AGENTS", "3"))),
            agent_max_turns=max(1, int(os.getenv("AGENT_MAX_TURNS", "12"))),
            agent_timeout_seconds=max(30, int(os.getenv("AGENT_TIMEOUT_SECONDS", "900"))),
            max_graph_iterations=max(5, int(os.getenv("MAX_GRAPH_ITERATIONS", "20"))),
            max_replan_iterations=max(1, int(os.getenv("MAX_REPLAN_ITERATIONS", "3"))),
            max_task_revisions=max(1, int(os.getenv("MAX_TASK_REVISIONS", "2"))),
        )

# 单例化配置对象，供全局使用。
settings = Settings.from_env()
