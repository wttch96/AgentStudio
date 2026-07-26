"""显式依赖容器，避免在各模块散布全局单例。"""

import logging
from dataclasses import dataclass

from app.agents.chat_executor import ChatExecutor
from app.agents.claude_executor import ClaudeAgentExecutor
from app.agents.file_agent_executor import FileAgentExecutor
from app.agents.rag_executor import RAGAgentExecutor
from app.agents.registry import AgentRegistry
from app.agents.skill_registry import SkillRegistry
from app.agents.todo_agent import TodoStore
from app.agents.agent_context import AgentContextBuilder
from app.agents.agent_selector import AgentSelector
from app.config import Settings
from app.domain.configuration import SchedulerConfiguration
from app.events.publisher import EventPublisher
from app.flow_engine.engine import FlowEngine
from app.flow_engine.yaml_compiler import YamlCompiler
from app.flow_engine.templates import FlowTemplateRenderer
from app.orchestration.reviewer import WaveReviewer
from app.orchestration.concurrency import ConflictDetector
from app.planning.deepseek_planner import DeepSeekPlanner
from app.services.blackboard_store import BlackboardStore
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

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ServiceContainer:
    settings: Settings
    store: SQLiteStore
    events: EventPublisher
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
    blackboard_store: BlackboardStore
    todo_store: TodoStore
    yaml_compiler: YamlCompiler
    rag_executor: RAGAgentExecutor | None
    chat_executor: ChatExecutor | None
    file_agent_executor: FileAgentExecutor | None
    # ── 新增组件 ──
    agent_selector: AgentSelector | None = None
    agent_context_builder: AgentContextBuilder | None = None
    reviewer: WaveReviewer | None = None
    conflict_detector: ConflictDetector | None = None

    @classmethod
    def build(cls, settings: Settings) -> "ServiceContainer":
        logger.info(
            "services.building database=%s current_project=%s deepseek=%s claude_route=%s",
            settings.database_path,
            settings._read_current_project() or "-",
            bool(settings.deepseek_api_key),
            settings.claude_route,
        )
        store = SQLiteStore(settings.database_path)
        recovered = store.recover_interrupted_runs()
        if recovered:
            logger.warning("services.recovered_interrupted_runs count=%s", recovered)
        events = EventPublisher(store)

        # File-first configuration layer (.workspace/<project-id>/)
        config_reader = ConfigReader(settings.workspace_root)

        registry = AgentRegistry(store, config_reader=config_reader)
        skills = SkillRegistry(
            settings.workspace_root / ".claude" / "skills", config_reader=config_reader
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
        flow_store = FlowStore(
            config_reader.current().flows_dir,
            store=store,
            fallback_dir=settings.workspace_root / "templates" / "flows",
        )
        planner = DeepSeekPlanner(settings, brain, knowledge_store=knowledge_store)
        executor = ClaudeAgentExecutor(settings, registry, events)
        memory_settings = MemorySettings(config_reader=config_reader)
        memory_manager = MemoryManager(settings, store, memory_settings.current())
        interrupt_router = InterruptRouter(store, events)
        project_manager = ProjectManager(store, config_reader=config_reader)
        rag_executor = RAGAgentExecutor(settings, registry, events, knowledge_store) if settings.deepseek_api_key else None
        chat_executor = ChatExecutor(settings, registry, events) if settings.deepseek_api_key else None
        file_agent_executor = FileAgentExecutor(settings, registry, events) if settings.deepseek_api_key else None

        # ---- New infrastructure: Blackboard + Todo + YamlCompiler ----
        blackboard_store = BlackboardStore(store)
        todo_store = TodoStore(blackboard_store)
        # ── 新增组件 ──
        agent_selector = AgentSelector(registry)
        agent_context_builder = AgentContextBuilder(
            blackboard_store=blackboard_store,
            todo_store=todo_store,
            agent_registry=registry,
        )
        reviewer = WaveReviewer(
            planner=planner,
            blackboard_store=blackboard_store,
            events=events,
            enable_llm_review=False,
        )
        conflict_detector = ConflictDetector()

        template_renderer = FlowTemplateRenderer()
        yaml_compiler = YamlCompiler(
            executor=executor,
            rag_executor=rag_executor,
            chat_executor=chat_executor,
            file_agent_executor=file_agent_executor,
            events=events,
            flow_store=flow_store,
            blackboard_store=blackboard_store,
            todo_store=todo_store,
            template_renderer=template_renderer,
        )

        # Legacy flow engine (kept as fallback)
        flow_engine = FlowEngine(executor, events, store, flow_store=flow_store, rag_executor=rag_executor, chat_executor=chat_executor, file_agent_executor=file_agent_executor)

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
            chat_executor=chat_executor,
            file_agent_executor=file_agent_executor,
            flow_engine=flow_engine,
            blackboard_store=blackboard_store,
            todo_store=todo_store,
            yaml_compiler=yaml_compiler,
            flow_store=flow_store,
            reviewer=reviewer,
            agent_context_builder=agent_context_builder,
            conflict_detector=conflict_detector,
            agent_selector=agent_selector,
            settings=settings,
        )
        container = cls(
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
            blackboard_store,
            todo_store,
            yaml_compiler,
            rag_executor,
            chat_executor,
            file_agent_executor,
            agent_selector=agent_selector,
            agent_context_builder=agent_context_builder,
            reviewer=reviewer,
            conflict_detector=conflict_detector,
        )
        logger.info(
            "services.ready rag_executor=%s chat_executor=%s file_executor=%s",
            rag_executor is not None,
            chat_executor is not None,
            file_agent_executor is not None,
        )
        return container
