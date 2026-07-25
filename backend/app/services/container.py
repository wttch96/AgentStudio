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
from app.flow_engine.engine import FlowEngine
from app.planning.deepseek_planner import DeepSeekPlanner
from app.services.brain_settings import BrainSettings
from app.services.config_reader import ConfigReader
from app.services.deepseek_balance import DeepSeekBalanceService
from app.services.interrupt_router import InterruptRouter
from app.services.knowledge_store import KnowledgeStore
from app.services.flow_store import FlowStore
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
    # File-backed configuration
    config_reader: ConfigReader
    registry: AgentRegistry
    skills: SkillRegistry
    workspace: WorkspaceSettings
    scheduler: SchedulerSettings
    brain: BrainSettings
    deepseek_balance: DeepSeekBalanceService
    planner: DeepSeekPlanner
    executor: ClaudeAgentExecutor
    memory_settings: MemorySettings
    memory_manager: MemoryManager
    interrupt_router: InterruptRouter
    runs: RunManager
    project_manager: ProjectManager
    knowledge_store: KnowledgeStore
    flow_store: FlowStore
    flow_engine: FlowEngine
    rag_executor: RAGAgentExecutor | None
    file_agent_executor: FileAgentExecutor | None

    @classmethod
    def build(cls, settings: Settings) -> "ServiceContainer":
        store = SQLiteStore(settings.database_path)
        store.recover_interrupted_runs()
        events = EventPublisher(store)

        # File-first configuration layer (.workspace/.agent-studio/)
        config_reader = ConfigReader(settings.workspace_root)
        # Migrate existing DB data to .agent-studio/ on first launch
        try:
            config_reader.migrate_from_db(store)
        except Exception:
            pass

        registry = AgentRegistry(store, config_reader=config_reader)
        skills = SkillRegistry(
            settings.workspace_root / ".claude" / "skills", store=store
        )
        workspace = WorkspaceSettings(
            config_reader=config_reader,
            default_root=settings.workspace_root,
        )
        scheduler = SchedulerSettings(
            config_reader=config_reader,
            defaults=SchedulerConfiguration(
                max_concurrent_agents=settings.max_concurrent_agents,
                recursion_limit=100,
                agent_max_turns=settings.agent_max_turns,
                agent_timeout_seconds=settings.agent_timeout_seconds,
            ),
        )
        brain = BrainSettings(
            config_reader=config_reader,
            defaults_path=settings.workspace_root / "templates" / "brain.default.json",
        )
        deepseek_balance = DeepSeekBalanceService(settings)
        knowledge_store = KnowledgeStore(store, settings)
        flow_store = FlowStore(settings.workspace_root / "templates" / "flows", store=store)
        planner = DeepSeekPlanner(settings, brain, knowledge_store=knowledge_store)
        executor = ClaudeAgentExecutor(settings, registry, events)
        memory_settings = MemorySettings(config_reader=config_reader)
        memory_manager = MemoryManager(settings, store, memory_settings.current())
        interrupt_router = InterruptRouter(store, events)
        project_manager = ProjectManager(store, config_reader=config_reader)
        rag_executor = RAGAgentExecutor(settings, registry, events, knowledge_store) if settings.deepseek_api_key else None
        file_agent_executor = FileAgentExecutor(settings, registry, events) if settings.deepseek_api_key else None
        flow_engine = FlowEngine(executor, events, store, flow_store=flow_store, rag_executor=rag_executor, file_agent_executor=file_agent_executor)
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
            flow_engine=flow_engine,
        )
        return cls(
            settings,
            store,
            events,
            config_reader,
            registry,
            skills,
            workspace,
            scheduler,
            brain,
            deepseek_balance,
            planner,
            executor,
            memory_settings,
            memory_manager,
            interrupt_router,
            runs,
            project_manager,
            knowledge_store,
            flow_store,
            flow_engine,
            rag_executor,
            file_agent_executor,
        )
