"""显式依赖容器，避免在各模块散布全局单例。"""

from dataclasses import dataclass

from app.agents.claude_executor import ClaudeAgentExecutor
from app.agents.registry import AgentRegistry
from app.agents.skill_registry import SkillRegistry
from app.config import Settings
from app.domain.configuration import SchedulerConfiguration
from app.events.publisher import EventPublisher
from app.planning.deepseek_planner import DeepSeekPlanner
from app.services.deepseek_balance import DeepSeekBalanceService
from app.services.deepseek_usage import DeepSeekUsageService
from app.services.run_manager import RunManager
from app.services.scheduler_settings import SchedulerSettings
from app.services.workspace_settings import WorkspaceSettings
from app.storage.sqlite_store import SQLiteStore


@dataclass(slots=True)
class ServiceContainer:
    settings: Settings
    store: SQLiteStore
    events: EventPublisher
    registry: AgentRegistry
    skills: SkillRegistry
    workspace: WorkspaceSettings
    scheduler: SchedulerSettings
    deepseek_balance: DeepSeekBalanceService
    deepseek_usage: DeepSeekUsageService
    planner: DeepSeekPlanner
    executor: ClaudeAgentExecutor
    runs: RunManager

    @classmethod
    def build(cls, settings: Settings) -> "ServiceContainer":
        store = SQLiteStore(settings.database_path)
        # 新进程不可能恢复旧进程中的 daemon worker，先清理遗留运行状态。
        store.recover_interrupted_runs()
        events = EventPublisher(store)
        registry = AgentRegistry(settings.workspace_root / "agents")
        skills = SkillRegistry(settings.workspace_root / ".claude" / "skills")
        workspace = WorkspaceSettings(
            settings.instance_dir / "workspace.json", settings.workspace_root
        )
        scheduler = SchedulerSettings(
            settings.instance_dir / "scheduler.json",
            SchedulerConfiguration(
                max_concurrent_agents=settings.max_concurrent_agents,
                recursion_limit=100,
                agent_max_turns=settings.agent_max_turns,
                agent_timeout_seconds=settings.agent_timeout_seconds,
            ),
        )
        deepseek_balance = DeepSeekBalanceService(settings)
        deepseek_usage = DeepSeekUsageService(settings, store)
        planner = DeepSeekPlanner(settings, deepseek_usage)
        executor = ClaudeAgentExecutor(settings, registry, events)
        runs = RunManager(
            store,
            events,
            planner,
            executor,
            workspace,
            scheduler,
        )
        return cls(
            settings,
            store,
            events,
            registry,
            skills,
            workspace,
            scheduler,
            deepseek_balance,
            deepseek_usage,
            planner,
            executor,
            runs,
        )
