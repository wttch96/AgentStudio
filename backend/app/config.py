"""集中管理环境配置，并对危险监听地址进行前置校验。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_ROOT.parent


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
    max_concurrent_agents: int = 3
    agent_max_turns: int = 12
    agent_timeout_seconds: int = 900
    workspace_root: Path = WORKSPACE_ROOT

    @property
    def instance_dir(self) -> Path:
        return self.workspace_root / ".workspace" / "db"

    @property
    def database_path(self) -> Path:
        return self.instance_dir / "agents-manager.db"

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
        )
