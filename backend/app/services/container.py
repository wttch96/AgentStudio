"""显式依赖容器，避免在各模块散布全局单例。"""

from dataclasses import dataclass

from app.agents.claude_executor import ClaudeAgentExecutor
from app.agents.file_agent_executor import FileAgentExecutor
from app.agents.rag_executor import RAGAgentExecutor
from app.agents.registry import AgentRegistry
from app.agents.skill_registry import SkillRegistry
from app.config import Settings
from app.domain.configuration import SchedulerConfiguration
from app.events.publisher import EventPublisher
from app.planning.deepseek_planner import DeepSeekPlanner
from app.services.brain_settings import BrainSettings
from app.services.deepseek_balance import DeepSeekBalanceService
from app.services.deepseek_usage import DeepSeekUsageService
from app.services.interrupt_router import InterruptRouter
from app.services.knowledge_store import KnowledgeStore
from app.services.memory_manager import MemoryManager
from app.services.memory_settings import MemorySettings
from app.services.project_manager import ProjectManager
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
    brain: BrainSettings
    deepseek_balance: DeepSeekBalanceService
    deepseek_usage: DeepSeekUsageService
    planner: DeepSeekPlanner
    executor: ClaudeAgentExecutor
    memory_settings: MemorySettings
    memory_manager: MemoryManager
    interrupt_router: InterruptRouter
    runs: RunManager
    project_manager: ProjectManager
    knowledge_store: KnowledgeStore
    rag_executor: RAGAgentExecutor | None
    file_agent_executor: FileAgentExecutor | None

    @classmethod
    def build(cls, settings: Settings) -> "ServiceContainer":
        store = SQLiteStore(settings.database_path)
        # 新进程不可能恢复旧进程中的 daemon worker，先清理遗留运行状态。
        store.recover_interrupted_runs()
        events = EventPublisher(store)
        registry = AgentRegistry(store)
        skills = SkillRegistry(
            settings.workspace_root / ".claude" / "skills", store=store
        )
        workspace = WorkspaceSettings(
            config_path=settings.instance_dir / "workspace.json",
            default_root=settings.workspace_root,
            store=store,
        )
        scheduler = SchedulerSettings(
            config_path=settings.instance_dir / "scheduler.json",
            defaults=SchedulerConfiguration(
                max_concurrent_agents=settings.max_concurrent_agents,
                recursion_limit=100,
                agent_max_turns=settings.agent_max_turns,
                agent_timeout_seconds=settings.agent_timeout_seconds,
            ),
            store=store,
        )
        brain = BrainSettings(
            store=store,
            defaults_path=settings.workspace_root / "config" / "brain.default.json",
            config_path=settings.instance_dir / "brain.json",
        )
        deepseek_balance = DeepSeekBalanceService(settings)
        deepseek_usage = DeepSeekUsageService(settings, store)
        knowledge_store = KnowledgeStore(store, settings)
        planner = DeepSeekPlanner(settings, deepseek_usage, brain, knowledge_store=knowledge_store)
        executor = ClaudeAgentExecutor(settings, registry, events)
        memory_settings = MemorySettings(
            config_path=settings.instance_dir / "memory.json", store=store
        )
        memory_manager = MemoryManager(settings, store, memory_settings.current())
        interrupt_router = InterruptRouter(store, events)
        project_manager = ProjectManager(store)
        rag_executor = RAGAgentExecutor(settings, registry, events, knowledge_store) if settings.deepseek_api_key else None
        file_agent_executor = FileAgentExecutor(settings, registry, events) if settings.deepseek_api_key else None
        runs = RunManager(
            store,
            events,
            planner,
            executor,
            workspace,
            scheduler,
            memory_manager,
            interrupt_router,
            rag_executor=rag_executor,
            file_agent_executor=file_agent_executor,
        )
        return cls(
            settings,
            store,
            events,
            registry,
            skills,
            workspace,
            scheduler,
            brain,
            deepseek_balance,
            deepseek_usage,
            planner,
            executor,
            memory_settings,
            memory_manager,
            interrupt_router,
            runs,
            project_manager,
            knowledge_store,
            rag_executor,
            file_agent_executor,
        )
