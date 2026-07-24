# Agents Manager Backend — 结构化分析文档

> 生成日期：2026-07-23
> 项目名称：`agents-manager-backend`
> 项目路径：`/Users/wttch/workspace/AgentsManager/backend/`
> 项目描述：Local-only DeepSeek, LangGraph and Claude Agent SDK orchestrator

---

## 目录

1. [技术栈全景](#1-技术栈全景)
2. [项目架构](#2-项目架构)
3. [目录结构](#3-目录结构)
4. [关键入口](#4-关键入口)
5. [REST API 路由](#5-rest-api-路由)
6. [SSE 事件协议](#6-sse-事件协议)
7. [数据库 Schema](#7-数据库-schema)
8. [领域模型](#8-领域模型)
9. [业务服务](#9-业务服务)
10. [Agent 执行体系](#10-agent-执行体系)
11. [测试覆盖分析](#11-测试覆盖分析)
12. [安全与配置](#12-安全与配置)
13. [关键观察与建议](#13-关键观察与建议)

---

## 1. 技术栈全景

### 1.1 运行时与语言

| 维度 | 版本 | 说明 |
|------|------|------|
| Python | >= 3.11 | `requires-python` 最低要求 |
| WSGI | Werkzeug (Flask 内置) | 开发/本地部署 |

### 1.2 核心依赖

| 依赖 | 版本约束 | 用途 |
|------|----------|------|
| `flask` | >= 3.1.0, < 4.0.0 | Web 框架 |
| `flask-cors` | >= 5.0.0, < 7.0.0 | CORS 中间件，前后端分端口部署 |
| `langgraph` | >= 1.0.0, < 2.0.0 | DAG 任务编排状态图 |
| `claude-agent-sdk` | >= 0.2.0, < 0.3.0 | Claude Agent 执行器 |
| `openai` | >= 1.60.0, < 3.0.0 | DeepSeek API / OpenAI 兼容客户端 |
| `pydantic` | >= 2.10.0, < 3.0.0 | 领域模型 & 配置校验 |
| `httpx` | >= 0.27.0, < 1.0.0 | HTTP 客户端（DeepSeek 余额查询） |
| `python-dotenv` | >= 1.0.0, < 2.0.0 | 环境变量加载 |
| `pyyaml` | >= 6.0.0, < 7.0.0 | YAML 解析（Agent 配置） |

### 1.3 可选依赖

| 依赖 | 版本约束 | 用途 |
|------|----------|------|
| `pytest` | >= 8.0.0, < 10.0.0 | 测试框架 |
| `ruff` | >= 0.9.0, < 1.0.0 | 代码检查与格式化 |

### 1.4 外部集成

| 系统 | 用途 | 配置方式 |
|------|------|----------|
| DeepSeek API | 主脑规划（DAG 生成 + 验收汇总）、Token 用量估算 | `DEEPSEEK_API_KEY` + `DEEPSEEK_BASE_URL` |
| Anthropic Claude API | Agent 执行（直连或 CC Switch 代理） | `ANTHROPIC_API_KEY` 或 `ANTHROPIC_AUTH_TOKEN` |
| SQLite 3 | 本地持久化（WAL 模式，支持并发读写） | 内置 `sqlite3`，无需外部数据库 |
| LangChain | DeepSeek Agent / RAG Agent 的工具型 Agent 框架 | 可选（DeepSeek executor） |
| LangMem | 跨会话长期记忆提取和会话摘要 | 可选（需要 DeepSeek API） |
| sqlite-vec | 知识库向量检索（可选扩展） | 运行时检测，不可用时降级为 BM25 |

---

## 2. 项目架构

### 2.1 整体架构风格

**Flask Blueprint + 显式 Service Container DI** —— 没有使用 Flask 全局代理对象（`current_app` 仅限于路由层获取容器），不依赖 Flask-SQLAlchemy 等第三方扩展。

```
┌─────────────────────────────────────────────────────┐
│                    HTTP Request                      │
│                        │                             │
│                 Flask Blueprint                      │
│              (app/api/routes.py)                     │
│                        │                             │
│           ServiceContainer (显式 DI)                  │
│         ┌──────┬──────┬──────┬──────┬───┐            │
│         │Runs  │Planner│Memory│Knowledge│... │            │
│         └──┬───┴──┬───┴──┬───┴──┬───┴───┘            │
│            │      │      │      │                     │
│         ┌──▼──┐┌──▼──┐┌──▼──┐┌──▼──┐                 │
│         │SQLite││Lang ││Lang ││Deep │                 │
│         │Store ││Graph││Chain││Seek │                 │
│         └─────┘└─────┘└─────┘└─────┘                 │
└─────────────────────────────────────────────────────┘
```

### 2.2 架构层次

| 层次 | 目录 | 职责 |
|------|------|------|
| **表现层** | `app/api/` | REST 路由、请求校验、错误映射 |
| **应用层** | `app/services/` | 服务编排、运行管理、配置持久化 |
| **领域层** | `app/domain/` | Pydantic 模型、配置 Schema、值对象 |
| **基础设施** | `app/storage/` | SQLite 持久化、内存状态、FTS5 全文索引 |
| **编排层** | `app/orchestration/` | LangGraph 状态图定义（计划→并行→汇流→归约） |
| **规划层** | `app/planning/` | DeepSeek 主脑规划（DAG 生成、工作总结） |
| **Agent 层** | `app/agents/` | Claude / DeepSeek / RAG Agent 执行器 + 注册表 |
| **事件层** | `app/events/` | 统一事件发布（持久化到 SQLite + SSE 推送） |

### 2.3 依赖注入

通过 `ServiceContainer`（`app/services/container.py`）集中构建所有服务实例，避免模块间全局单例。容器在 `create_app()` 中创建并挂载到 `app.extensions["services"]`，路由层通过 `services()` helper 函数获取。

依赖图（按构造顺序）：

```
Settings
  └─ SQLiteStore
      └─ EventPublisher
      └─ AgentRegistry
      └─ SkillRegistry
      └─ WorkspaceSettings
      └─ SchedulerSettings
      └─ BrainSettings
      └─ MemorySettings
      └─ KnowledgeStore → SQLiteStore + Settings
      └─ DeepSeekPlanner → Settings + DeepSeekUsageService + BrainSettings + KnowledgeStore
      └─ ClaudeAgentExecutor → Settings + AgentRegistry + EventPublisher
      └─ MemoryManager → Settings + SQLiteStore + MemoryConfiguration
      └─ InterruptRouter → SQLiteStore + EventPublisher
      └─ ProjectManager → SQLiteStore
      └─ DeepSeekAgentExecutor (条件创建)
      └─ RAGAgentExecutor (条件创建)
      └─ RunManager → 以上全部
```

### 2.4 运行生命周期

```
用户 POST /api/runs
  ↓
RunManager.start()
  ├── parse_run_command()  → 解析斜杠命令（/frontend, /retry 等）
  ├── 创建工作目录、创建 SQLite 运行记录
  ├── 启动 daemon 线程
  └── 立即返回 HTTP 202（异步）
        ↓
LangGraph 状态机 (daemon thread)
  1. plan        → DeepSeek 生成 DAG 或使用预设 DAG
  2. interrupt_check → 检查用户中断指令
  3. scheduler   → 计算当前 wave 就绪任务
  4. worker(并行)  → Claude/DeepSeek/RAG Agent 执行
  5. barrier     → wave 汇流屏障
  6. compact_memory → 滑动窗口压缩
  7. [如果 discovery 阶段] replan_after_discovery
  8. synthesize  → DeepSeek 验收汇总
  9. extract_memory → LangMem 长期记忆提取
  ↓
更新运行状态 → 前端通过 SSE 实时接收事件
```

---

## 3. 目录结构

```
backend/
├── run.py                          # 本地开发入口
├── pyproject.toml                  # 项目元数据、依赖、pytest/ruff 配置
├── app/
│   ├── __init__.py                 # Flask 应用工厂 (create_app)
│   ├── config.py                   # Settings dataclass (环境变量→配置)
│   ├── api/
│   │   └── routes.py               # ~640 行，全部 REST + SSE 端点
│   ├── domain/
│   │   ├── models.py               # Pydantic 领域模型 (280 行)
│   │   └── configuration.py        # 配置中心输入模型 (75 行)
│   ├── storage/
│   │   └── sqlite_store.py         # SQLite CRUD ~950 行
│   ├── events/
│   │   └── publisher.py            # 统一事件发布 (30 行)
│   ├── planning/
│   │   └── deepseek_planner.py     # DeepSeek DAG 规划器 (438 行)
│   ├── orchestration/
│   │   └── graph.py                # LangGraph 状态图 (474 行)
│   ├── agents/
│   │   ├── claude_executor.py      # Claude Agent SDK 适配器 (269 行)
│   │   ├── deepseek_executor.py    # DeepSeek LangChain Agent (250 行)
│   │   ├── rag_executor.py         # RAG LangChain Agent (216 行)
│   │   ├── registry.py             # Agent 注册表 (123 行)
│   │   └── skill_registry.py       # Skill 注册表
│   └── services/
│       ├── container.py            # ServiceContainer DI (128 行)
│       ├── run_manager.py          # 运行生命周期管理 (352 行)
│       ├── run_commands.py         # 斜杠命令解析 (63 行)
│       ├── project_manager.py      # 项目 + Agent 模板 CRUD (362 行)
│       ├── knowledge_store.py      # 知识库混合检索 (173 行)
│       ├── memory_manager.py       # LangMem 分层记忆 (347 行)
│       ├── memory_settings.py      # 记忆系统配置持久化
│       ├── brain_settings.py       # 主脑提示词持久化 (104 行)
│       ├── scheduler_settings.py   # 调度参数持久化
│       ├── workspace_settings.py   # 工作目录持久化 + 目录浏览 (80 行)
│       ├── deepseek_balance.py     # DeepSeek 余额查询
│       ├── deepseek_usage.py       # DeepSeek 用量统计
│       └── interrupt_router.py     # 中断指令路由 (90 行)
├── instance/                       # 运行期数据目录 (gitignored)
│   ├── agents-manager.db           # SQLite 数据库文件
│   ├── brain.json                  # 主脑配置 (旧文件格式，已迁移到 SQLite)
│   ├── scheduler.json              # 调度参数
│   ├── memory.json                 # 记忆配置
│   └── workspace.json              # 工作目录配置
└── tests/
    ├── conftest.py                 # pytest fixtures (app, client)
    ├── test_api.py                 # 集成测试 ~367 行
    ├── test_graph_parallelism.py   # LangGraph 并行/汇流测试
    ├── test_planner_routing.py     # DeepSeek 规划器路由测试
    ├── test_brain_settings.py      # 主脑配置持久化测试
    ├── test_run_commands.py        # 斜杠命令解析测试
    ├── test_deepseek_balance.py    # DeepSeek 余额测试
    └── test_deepseek_usage.py      # DeepSeek 用量测试
```

---

## 4. 关键入口

### 4.1 开发启动入口

**`run.py`** —— 本地开发服务器启动点：

```python
from app import create_app
from app.config import Settings

settings = Settings.from_env()
app = create_app(settings)

if __name__ == "__main__":
    app.run(host=settings.backend_host, port=settings.backend_port,
            threaded=True, debug=False)
```

- 监听地址强制校验为回环地址（`127.0.0.1` / `localhost` / `::1`）
- `threaded=True`：每个请求独立线程，配合 SQLite WAL 模式支持并发
- 生产部署应使用 WSGI 服务器替代 `app.run()`

### 4.2 应用工厂

**`app/__init__.py` —— `create_app()`**：

```python
def create_app(settings: Settings | None = None) -> Flask:
    # 1. 加载配置（支持测试时注入独立配置）
    # 2. 配置 JSON 响应不排序
    # 3. CORS 允许前后端回环地址
    # 4. 构建 ServiceContainer DI
    # 5. 注册 API Blueprint (/api)
    # 6. 注册健康检查端点 (/health)
```

### 4.3 配置加载

**`app/config.py` —— `Settings`**：

- `@dataclass(frozen=True, slots=True)` —— 不可变配置对象
- 从 `.env` 文件加载（项目根目录的 `.env`）
- API Key 仅保存在进程内存中，任何 API 响应都只返回 `bool`（"是否已配置"）
- 强制检查 `BACKEND_HOST` 必须为回环地址
- 提供 `demo_mode` 属性（未配置 DeepSeek + Claude 时为 `True`）
- 提供 `claude_route` 属性（`direct` / `cc-switch` / `custom`）

---

## 5. REST API 路由

所有 API 路由位于 `app/api/routes.py`，注册于 `/api` 前缀，单一 Blueprint `api`。

### 5.1 系统状态

| 方法 | 路径 | 说明 | 控制器函数 |
|------|------|------|-----------|
| GET | `/api/status` | 系统运行状态和模型配置（不暴露密钥） | `status()` |
| GET | `/health` | 健康检查（无 /api 前缀） | `health()`（在 `app/__init__.py` 定义） |

### 5.2 Agent 管理

| 方法 | 路径 | 说明 | 控制器函数 |
|------|------|------|-----------|
| GET | `/api/agents` | Agent 列表（支持 `?project_id=` 过滤） | `agents()` |
| GET | `/api/agents/<name>` | Agent 详情（需 `project_id` 参数） | `get_agent()` |
| PUT | `/api/agents/<name>` | **已废弃**，返回 400 提示使用项目 Agent 接口 | `update_agent()` |

### 5.3 Skill 管理

| 方法 | 路径 | 说明 | 控制器函数 |
|------|------|------|-----------|
| GET | `/api/skills` | Skill 列表（支持 `?project_id=`） | `skills()` |
| GET | `/api/skills/<name>` | Skill 详情 | `get_skill()` |
| POST | `/api/skills` | 创建 Skill | `create_skill()` |
| PUT | `/api/skills/<name>` | 更新 Skill | `update_skill()` |

### 5.4 工作目录

| 方法 | 路径 | 说明 | 控制器函数 |
|------|------|------|-----------|
| GET | `/api/workspace` | 获取当前工作目录路径 | `get_workspace()` |
| PUT | `/api/workspace` | 设置工作目录 | `update_workspace()` |
| GET | `/api/workspace/directories` | 目录树浏览 | `browse_workspace()` |

### 5.5 调度配置

| 方法 | 路径 | 说明 | 控制器函数 |
|------|------|------|-----------|
| GET | `/api/scheduler` | 读取调度参数 | `get_scheduler()` |
| PUT | `/api/scheduler` | 更新调度参数 | `update_scheduler()` |

### 5.6 主脑配置

| 方法 | 路径 | 说明 | 控制器函数 |
|------|------|------|-----------|
| GET | `/api/brain` | 读取主脑提示词 | `get_brain()` |
| GET | `/api/brain/default` | 读取默认主脑提示词 | `get_default_brain()` |
| PUT | `/api/brain` | 更新主脑提示词 | `update_brain()` |

### 5.7 DeepSeek 工具

| 方法 | 路径 | 说明 | 控制器函数 |
|------|------|------|-----------|
| GET | `/api/deepseek/balance` | 查询余额（支持 `?refresh=1` 强制刷新） | `deepseek_balance()` |
| GET | `/api/deepseek/usage` | Token 用量统计（按天/月/全部） | `deepseek_usage()` |

### 5.8 运行管理

| 方法 | 路径 | 说明 | 控制器函数 |
|------|------|------|-----------|
| POST | `/api/runs` | 创建运行（异步，返回 202） | `create_run()` |
| GET | `/api/runs` | 运行列表 | `list_runs()` |
| GET | `/api/runs/<id>` | 运行详情（含事件列表） | `get_run()` |
| DELETE | `/api/runs/<id>` | 删除运行（级联删除事件） | `delete_run()` |
| POST | `/api/runs/<id>/cancel` | 取消运行 | `cancel_run()` |
| GET | `/api/runs/<id>/events` | 运行事件列表（支持 `?after=` 分页） | `list_events()` |
| GET | `/api/runs/<id>/stream` | SSE 事件流（实时推送） | `stream_events()` |
| POST | `/api/runs/<id>/interrupt` | 发送中断指令 | `send_interrupt()` |
| POST | `/api/runs/<id>/resume` | 恢复中断的运行 | `resume_run()` |

### 5.9 记忆配置

| 方法 | 路径 | 说明 | 控制器函数 |
|------|------|------|-----------|
| GET | `/api/memory` | 读取记忆系统配置 | `get_memory_config()` |
| PUT | `/api/memory` | 更新记忆系统配置 | `update_memory_config()` |
| GET | `/api/memory/stats/<conversation_id>` | 对话记忆统计 | `get_memory_stats()` |

### 5.10 知识库

| 方法 | 路径 | 说明 | 控制器函数 |
|------|------|------|-----------|
| GET | `/api/knowledge` | 搜索/列出知识条目（支持 `?q=&category=&top_k=`） | `search_knowledge()` |
| GET | `/api/knowledge/<id>` | 知识条目详情 | `get_knowledge()` |
| POST | `/api/knowledge` | 创建知识条目 | `create_knowledge()` |
| PUT | `/api/knowledge/<id>` | 更新知识条目 | `update_knowledge()` |
| DELETE | `/api/knowledge/<id>` | 删除知识条目 | `delete_knowledge()` |
| GET | `/api/knowledge/<id>/relations` | 知识关联列表 | `get_knowledge_relations()` |
| POST | `/api/knowledge/relations` | 创建知识关联 | `create_knowledge_relation()` |
| POST | `/api/knowledge/<id>/feedback` | 知识反馈（up/down） | `add_knowledge_feedback()` |
| GET | `/api/knowledge-stats` | 知识库统计 | `knowledge_stats()` |
| POST | `/api/knowledge/cleanup` | 清理过期知识 | `cleanup_knowledge()` |

### 5.11 项目管理

| 方法 | 路径 | 说明 | 控制器函数 |
|------|------|------|-----------|
| GET | `/api/projects` | 项目列表 | `list_projects()` |
| POST | `/api/projects` | 创建项目 | `create_project()` |
| GET | `/api/projects/<id>` | 项目详情 | `get_project()` |
| DELETE | `/api/projects/<id>` | 删除项目 | `delete_project()` |
| GET | `/api/projects/<id>/agents` | 项目 Agent 列表 | `list_project_agents()` |
| POST | `/api/projects/<id>/agents` | 添加项目 Agent | `add_project_agent()` |
| PUT | `/api/projects/<id>/agents/<aid>` | 更新项目 Agent | `update_project_agent()` |
| DELETE | `/api/projects/<id>/agents/<aid>` | 删除项目 Agent | `delete_project_agent()` |

### 5.12 模板管理

| 方法 | 路径 | 说明 | 控制器函数 |
|------|------|------|-----------|
| GET | `/api/templates` | Agent 模板列表（支持 `?category=`） | `list_templates()` |
| POST | `/api/templates` | 创建模板 | `create_template()` |
| PUT | `/api/templates/<id>` | 更新模板 | `update_template()` |
| DELETE | `/api/templates/<id>` | 删除模板 | `delete_template()` |

### 5.13 模板中心

| 方法 | 路径 | 说明 | 控制器函数 |
|------|------|------|-----------|
| GET | `/api/template-center` | 模板中心聚合（Agent 模板 + Skill 模板） | `template_center()` |
| POST | `/api/template-center/skills` | 发布 Skill 模板 | `publish_skill_template()` |

---

## 6. SSE 事件协议

### 6.1 端点

`GET /api/runs/<run_id>/stream?after=<sequence>`

### 6.2 协议细节

| 属性 | 值 |
|------|-----|
| Content-Type | `text/event-stream` |
| Cache-Control | `no-cache` |
| X-Accel-Buffering | `no` |
| Connection | `keep-alive` |
| 心跳 | `: keep-alive\n\n`（每 3 秒 / 15 个空闲轮次） |
| 事件类型 | `run-event` |
| 序列号 | 按 run 单调递增，`sequence` 字段 |

### 6.3 事件类型

| 事件类型 | 阶段 | 说明 |
|----------|------|------|
| `run.started` | 启动 | 运行开始 |
| `run.completed` | 终态 | 运行成功完成 |
| `run.failed` | 终态 | 运行失败 |
| `run.cancelled` | 终态 | 运行被取消 |
| `run.cancel_requested` | 交互 | 取消请求已发送 |
| `run.summary` | 汇总 | 最终输出摘要 |
| `plan.created` | 规划 | DAG 任务计划生成（含 `stage`、`tasks`、`coordination_contract`） |
| `planner.started` | 规划 | DeepSeek 主脑规划中 |
| `planner.bypassed` | 规划 | 跳过主脑（直接 Agent / 重试模式） |
| `workspace.discovery_started` | 发现 | 项目发现开始 |
| `workspace.discovery_skipped` | 发现 | 无项目 Agent，跳过发现 |
| `brain.contract_created` | 规划 | 共享接口契约生成 |
| `brain.synthesizing` | 汇总 | DeepSeek 验收汇总中 |
| `wave.started` | 执行 | 新 wave 开始（并行任务批次） |
| `wave.completed` | 执行 | wave 完成 |
| `agent.started` | 执行 | Agent 开始执行 |
| `agent.completed` | 执行 | Agent 执行成功 |
| `agent.failed` | 执行 | Agent 执行失败 |
| `agent.message` | 执行 | Agent 中间消息 |
| `agent.usage` | 执行 | Agent Token / 费用消耗 |
| `tool.started` | 执行 | Agent 调用工具 |
| `skill.loaded` | 执行 | Agent 加载 Skill |
| `interrupt.requested` | 交互 | 中断指令已发送 |
| `interrupt.received` | 交互 | 图引擎已收到中断 |
| `interrupt.resolved` | 交互 | 中断已处理 |
| `memory.compacted` | 记忆 | 消息历史压缩 |
| `memory.extracted` | 记忆 | 长期记忆提取 |

### 6.4 SSE 事件格式

```json
// wire format (SSE)
id: 42
event: run-event
data: {"run_id":"abc123","sequence":42,"type":"agent.completed","timestamp":"2026-07-23T10:00:00+00:00","agent_id":"backend-agent","task_id":"implement-api","payload":{"summary":"完成", ...}}
```

---

## 7. 数据库 Schema

数据库文件：`instance/agents-manager.db`

存储引擎：SQLite 3，使用 WAL 模式，外键约束开启。

### 7.1 核心运行表

**`runs`** —— 运行记录

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | UUID hex |
| `objective` | TEXT | NOT NULL | 用户目标（2-20000 字符） |
| `workspace_root` | TEXT | | 运行使用的工作目录 |
| `parent_run_id` | TEXT | | 上游运行 ID（对话链） |
| `conversation_id` | TEXT | | 对话 ID（父子 run 共享） |
| `turn_index` | INTEGER | DEFAULT 1 NOT NULL | 对话轮次序号 |
| `status` | TEXT | NOT NULL | `queued` / `running` / `completed` / `failed` / `cancelled` |
| `final_answer` | TEXT | | 最终输出 |
| `error` | TEXT | | 错误详情 |
| `created_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |
| `updated_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |
| `started_at` | TEXT | (迁移添加) | 实际开始时间 |
| `project_id` | TEXT | REFERENCES projects(id) ON DELETE SET NULL (迁移添加) | 关联项目 |

**`events`** —— 运行时事件

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `run_id` | TEXT | NOT NULL, FK → runs(id) ON DELETE CASCADE | |
| `sequence` | INTEGER | NOT NULL, UNIQUE(run_id, sequence) | 单调递增序号 |
| `type` | TEXT | NOT NULL | 事件类型 |
| `timestamp` | TEXT | NOT NULL | ISO 8601 |
| `agent_id` | TEXT | | 关联 Agent |
| `task_id` | TEXT | | 关联任务 |
| `payload` | TEXT | NOT NULL | JSON 序列化 |

索引：`idx_events_run_sequence` ON `events(run_id, sequence)`

### 7.2 Token 用量表

**`deepseek_usage`** —— DeepSeek 请求用量记录

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `run_id` | TEXT | | |
| `phase` | TEXT | NOT NULL | `planning` / `synthesis` / `execution` |
| `model` | TEXT | NOT NULL | |
| `prompt_tokens` | INTEGER | NOT NULL | |
| `cache_hit_tokens` | INTEGER | NOT NULL | |
| `cache_miss_tokens` | INTEGER | NOT NULL | |
| `completion_tokens` | INTEGER | NOT NULL | |
| `total_tokens` | INTEGER | NOT NULL | |
| `estimated_cost_usd` | REAL | NOT NULL | 基于本地单价估算 |
| `occurred_at` | TEXT | NOT NULL | |

索引：`idx_deepseek_usage_occurred_at`

### 7.3 记忆系统表

**`memories`** —— 分层记忆记录

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | |
| `run_id` | TEXT | NOT NULL | |
| `conversation_id` | TEXT | NOT NULL | |
| `level` | TEXT | NOT NULL, CHECK(`agent`/`planner`/`session`/`project`) | 记忆层级 |
| `agent_id` | TEXT | | |
| `task_id` | TEXT | | |
| `phase` | TEXT | NOT NULL | `planning` / `execution` / `synthesis` / `compression` / `extraction` |
| `summary` | TEXT | NOT NULL | |
| `structured_data` | TEXT | | JSON |
| `token_count_before` | INTEGER | DEFAULT 0 | |
| `token_count_after` | INTEGER | DEFAULT 0 | |
| `importance` | REAL | DEFAULT 0.5 | [0.0, 1.0] |
| `created_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |

索引：
- `idx_memories_conversation` ON `memories(conversation_id, level, created_at)`
- `idx_memories_agent` ON `memories(agent_id, created_at)`

**`session_summaries`** —— 会话摘要

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `conversation_id` | TEXT | PK | |
| `title` | TEXT | | |
| `summary` | TEXT | NOT NULL | |
| `key_decisions` | TEXT | | JSON array |
| `total_turns` | INTEGER | DEFAULT 0 | |
| `total_tokens` | INTEGER | DEFAULT 0 | |
| `last_updated` | TEXT | DEFAULT CURRENT_TIMESTAMP | |

**`agent_memory_state`** —— Agent 记忆状态

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `agent_id` | TEXT | PK (复合) | |
| `conversation_id` | TEXT | PK (复合) | |
| `extracted_facts` | TEXT | DEFAULT '{}' | JSON |
| `token_budget` | INTEGER | DEFAULT 32000 | |
| `last_updated` | TEXT | DEFAULT CURRENT_TIMESTAMP | |

**`planner_memory_state`** —— 主脑记忆状态

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `conversation_id` | TEXT | PK | |
| `decision_log` | TEXT | DEFAULT '[]' | JSON |
| `agent_notes` | TEXT | DEFAULT '{}' | JSON |
| `project_notes` | TEXT | DEFAULT '{}' | JSON |
| `contract_history` | TEXT | DEFAULT '[]' | JSON |
| `last_updated` | TEXT | DEFAULT CURRENT_TIMESTAMP | |

### 7.4 中断指令表

**`interrupt_commands`** —— 用户中断指令

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | |
| `run_id` | TEXT | NOT NULL | |
| `target` | TEXT | NOT NULL | `all` / `agent` / `planner` |
| `action` | TEXT | NOT NULL | `pause` / `inject` / `replan` / `abort` / `resume` |
| `target_agent_id` | TEXT | | |
| `target_task_id` | TEXT | | |
| `instruction` | TEXT | DEFAULT '' | |
| `status` | TEXT | DEFAULT 'pending' | `pending` / `resolved` / `discarded` / `deferred` |
| `resolved_at` | TEXT | | |
| `created_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |

索引：`idx_interrupt_run` ON `interrupt_commands(run_id, status)`

### 7.5 项目管理表

**`projects`** —— 项目

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | |
| `name` | TEXT | NOT NULL | |
| `root_dir` | TEXT | NOT NULL | 项目工作目录 |
| `description` | TEXT | DEFAULT '' | |
| `created_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |
| `updated_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |

**`project_agents`** —— 项目 Agent

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | |
| `project_id` | TEXT | NOT NULL, FK → projects(id) ON DELETE CASCADE | |
| `name` | TEXT | NOT NULL, UNIQUE(project_id, name) | 标识符 |
| `display_name` | TEXT | NOT NULL | 显示名称 |
| `description` | TEXT | DEFAULT '' | |
| `template_id` | TEXT | | 来源模板 |
| `agent_type` | TEXT | NOT NULL, CHECK(`brain`/`rag`/`claude`/`deepseek`) | 执行器类型 |
| `sub_dir` | TEXT | DEFAULT '' | 子目录约束 |
| `system_prompt` | TEXT | NOT NULL | 系统提示词 |
| `tools` | TEXT | DEFAULT '[]' | JSON 工具列表 |
| `skills` | TEXT | DEFAULT '[]' | JSON Skill 列表 |
| `is_required` | INTEGER | DEFAULT 0 | 是否必选 |
| `sort_order` | INTEGER | DEFAULT 0 | 排序 |
| `created_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |
| `updated_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |

**`agent_templates`** —— Agent 模板

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | |
| `name` | TEXT | NOT NULL UNIQUE | |
| `display_name` | TEXT | NOT NULL | |
| `description` | TEXT | DEFAULT '' | |
| `category` | TEXT | NOT NULL | `frontend` / `backend` / `netty` / `other` |
| `agent_type` | TEXT | DEFAULT 'claude' | |
| `default_sub_dir` | TEXT | DEFAULT '' | |
| `default_prompt` | TEXT | NOT NULL | |
| `default_tools` | TEXT | DEFAULT '[]' | JSON |
| `default_skills` | TEXT | DEFAULT '[]' | JSON |
| `is_builtin` | INTEGER | DEFAULT 1 | 内置模板不可删除 |
| `created_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |

### 7.6 知识库表

**`knowledge_entries`** —— 知识条目

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | |
| `project_id` | TEXT | DEFAULT '' NOT NULL | 关联项目 |
| `title` | TEXT | NOT NULL | |
| `content` | TEXT | NOT NULL | |
| `category` | TEXT | DEFAULT 'general' | |
| `tags` | TEXT | DEFAULT '[]' | JSON |
| `source` | TEXT | DEFAULT '' | |
| `score` | REAL | DEFAULT 0.0 | 反馈评分 0-100 |
| `expires_at` | TEXT | | 过期时间 |
| `created_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |
| `updated_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |

**`knowledge_fts`** —— FTS5 全文索引（虚拟表）

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | TEXT | |
| `content` | TEXT | |
| `category` | TEXT | |
| `tags` | TEXT | |

关联触发器（自动同步 `knowledge_entries` → `knowledge_fts`）：
- `knowledge_fts_insert`：新增条目时自动插入 FTS
- `knowledge_fts_update`：更新条目时自动更新 FTS
- `knowledge_fts_delete`：删除条目时自动删除 FTS

**`knowledge_relations`** —— 知识关联

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | |
| `source_id` | TEXT | NOT NULL, FK → knowledge_entries(id) ON DELETE CASCADE | |
| `target_id` | TEXT | NOT NULL, FK → knowledge_entries(id) ON DELETE CASCADE | |
| `relation_type` | TEXT | NOT NULL | `api_example` / `error_handling` / `dependency` / `related` |
| `created_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |

UNIQUE 约束：`(source_id, target_id, relation_type)`

**`knowledge_feedback`** —— 知识反馈

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `entry_id` | TEXT | NOT NULL, FK → knowledge_entries(id) ON DELETE CASCADE | |
| `feedback` | TEXT | NOT NULL, CHECK(`up`/`down`) | |
| `created_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |

### 7.7 配置与 Skill 表

**`configs`** —— KV 配置存储

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `key` | TEXT | PK | |
| `value` | TEXT | NOT NULL | JSON 序列化 |
| `updated_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |

**`project_skills`** —— 项目级 Skill

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | |
| `project_id` | TEXT | NOT NULL, FK → projects(id) ON DELETE CASCADE | |
| `name` | TEXT | NOT NULL, UNIQUE(project_id, name) | |
| `description` | TEXT | DEFAULT '' | |
| `content` | TEXT | DEFAULT '' | |
| `created_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |
| `updated_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |

**`skill_templates`** —— Skill 模板中心

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | |
| `name` | TEXT | NOT NULL UNIQUE | |
| `display_name` | TEXT | NOT NULL | |
| `description` | TEXT | DEFAULT '' | |
| `category` | TEXT | DEFAULT 'general' | |
| `content` | TEXT | NOT NULL | |
| `is_builtin` | INTEGER | DEFAULT 0 | |
| `created_at` | TEXT | DEFAULT CURRENT_TIMESTAMP | |

---

## 8. 领域模型

### 8.1 核心模型 (`app/domain/models.py`)

| 模型 | 基类 | 说明 |
|------|------|------|
| `DagTask` | `BaseModel` | 最小任务单元（id, title, objective, agent, depends_on, write_scope） |
| `TaskDag` | `BaseModel` | 有向无环任务图（summary, coordination_contract, tasks）含循环依赖校验 |
| `AgentResult` | `BaseModel` | Agent 执行结果（task_id, agent, status, summary, changed_files, provides, error, started_at, duration_ms） |
| `RunEvent` | `BaseModel` | 统一事件（run_id, sequence, type, timestamp, agent_id, task_id, payload） |
| `CreateRunRequest` | `BaseModel` | 创建运行请求（objective, parent_run_id） |
| `MemoryLevel` | `Enum` | 记忆层级（agent / planner / session / project） |
| `MemoryRecord` | `BaseModel` | 单条记忆记录 |
| `AgentMemoryState` | `BaseModel` | Agent 完整记忆状态 |
| `PlannerMemoryState` | `BaseModel` | 主脑完整记忆状态 |
| `InterruptTarget` | `Enum` | 中断目标（all / agent / planner） |
| `InterruptAction` | `Enum` | 中断动作（pause / inject / replan / abort / resume） |
| `InterruptCommand` | `BaseModel` | 用户中断指令 |
| `InterruptDecision` | `BaseModel` | 中断处理决策 |
| `KnowledgeEntry` | `BaseModel` | 知识库条目 |
| `KnowledgeRelation` | `BaseModel` | 知识关联 |
| `KnowledgeFeedback` | `BaseModel` | 知识反馈 |
| `Project` | `BaseModel` | 项目 |
| `ProjectAgent` | `BaseModel` | 项目 Agent（含 agent_type: brain/rag/claude/deepseek） |
| `AgentTemplate` | `BaseModel` | Agent 模板 |
| `CreateProjectRequest` | `BaseModel` | 创建项目请求 |

### 8.2 配置模型 (`app/domain/configuration.py`)

| 模型 | 说明 | 字段 |
|------|------|------|
| `AgentUpdate` | Agent 配置更新校验 | description, tools(去重), skills(去重), prompt |
| `SkillCreate` | Skill 创建 | name(安全标识符), description, content |
| `SkillUpdate` | Skill 更新 | description, content |
| `WorkspaceUpdate` | 工作目录更新 | path |
| `BrainConfiguration` | 主脑提示词 | planning_prompt(50-50000), summary_prompt(20-30000) |
| `SchedulerConfiguration` | 调度参数 | max_concurrent_agents(1-8), recursion_limit(10-500), agent_max_turns(1-100), agent_timeout_seconds(30-7200) |
| `MemoryConfiguration` | 记忆系统配置 | agent_sliding_window, planner_sliding_window, compress_trigger_tokens, etc. |

---

## 9. 业务服务

### 9.1 服务清单

| 服务 | 文件 | 职责 |
|------|------|------|
| `RunManager` | `services/run_manager.py` | 运行生命周期（创建/取消/重试/继续），daemon 线程管理 |
| `ProjectManager` | `services/project_manager.py` | 项目 CRUD、Agent CRUD、模板管理、内置模板播种 |
| `KnowledgeStore` | `services/knowledge_store.py` | 知识库 CRUD、BM25+向量混合检索、RRF 融合、反馈评分、过期清理 |
| `MemoryManager` | `services/memory_manager.py` | LangMem 分层记忆（短期/长期/策略引擎） |
| `InterruptRouter` | `services/interrupt_router.py` | 中断指令队列、Agent 暂停/恢复信号 |
| `BrainSettings` | `services/brain_settings.py` | 主脑提示词持久化（SQLite / JSON 文件双后端） |
| `WorkspaceSettings` | `services/workspace_settings.py` | 工作目录持久化 + 目录树浏览 |
| `SchedulerSettings` | `services/scheduler_settings.py` | 调度参数持久化 |
| `MemorySettings` | `services/memory_settings.py` | 记忆配置持久化 |
| `DeepSeekBalanceService` | `services/deepseek_balance.py` | DeepSeek 余额查询（httpx + 缓存） |
| `DeepSeekUsageService` | `services/deepseek_usage.py` | DeepSeek 本地用量统计 |
| `EventPublisher` | `events/publisher.py` | 统一事件写入 SQLite |

### 9.2 内置 Agent 模板（8 个）

| 模板 ID | 名称 | 类型 | 子目录 | 描述 |
|---------|------|------|--------|------|
| `brain-template` | brain | brain | — | DeepSeek 主脑 |
| `rag-template` | knowledge-rag | rag | — | 知识库 RAG Agent |
| `vue-frontend-template` | vue-frontend | claude | frontend | Vue 3 + TypeScript 前端 |
| `react-frontend-template` | react-frontend | claude | frontend | React 前端 |
| `flask-backend-template` | flask-backend | claude | backend | Flask 后端 |
| `springboot-backend-template` | springboot-backend | claude | backend | SpringBoot 后端 |
| `springboot-netty-template` | springboot-netty | claude | netty | Netty 数据服务 |
| `deepseek-agent-template` | deepseek-agent | deepseek | — | DeepSeek 编码 Agent |

---

## 10. Agent 执行体系

### 10.1 三种执行器

| 执行器 | 驱动 | 适用场景 | 条件 |
|--------|------|----------|------|
| `ClaudeAgentExecutor` | Claude Agent SDK | 代码修改、文件读写、工具调用 | `claude_configured == True` |
| `DeepSeekAgentExecutor` | LangChain + ChatOpenAI | 编码、分析（Claude 不可用时） | `deepseek_api_key` 已配置 |
| `RAGAgentExecutor` | LangChain + ChatOpenAI | 知识库检索与录入 | `deepseek_api_key` 已配置 |

三种执行器通过 `agent_type`（`claude` / `deepseek` / `rag`）在 `graph.py` 的 `worker()` 节点中动态选择。

### 10.2 Agent 执行流程

```
worker(state)
  → 根据 task.agent 查找 AgentProfile
  → 收集前置依赖结果（dependency_results）
  → 解析 agent_type（claude / deepseek / rag）
  → 选择对应 executor
  → 发送 agent.started 事件
  → 调用 executor.execute()（异步 asyncio / 同步 demo）
  → 发送 agent.completed 或 agent.failed 事件
  → 返回 AgentResult（包含耗时统计）
```

### 10.3 Agent 注册表

`AgentRegistry` 从 `project_agents` 表加载配置，支持：
- 按 `project_id` 加载/缓存 Agent 列表
- 无 `project_id` 时遍历所有项目
- 只读缓存，配置变更后需调用 `invalidate()` 清除缓存

`AgentProfile` 使用 `__slots__` 优化内存，工具和技能使用 `tuple` 不可变存储。

---

## 11. 测试覆盖分析

### 11.1 测试文件清单

| 测试文件 | 类型 | 用例数 | 覆盖模块 |
|----------|------|--------|----------|
| `test_api.py` | 集成测试 | ~17 个 | 全部 REST 端点、运行生命周期、演示模式、重试、删除 |
| `test_graph_parallelism.py` | 单元测试 | 1 个（多断言） | LangGraph 并行分发与汇流屏障 |
| `test_planner_routing.py` | 单元测试 | 5 个 | DeepSeek 规划器 Agent 路由、领域排除、工作空间上下文 |
| `test_brain_settings.py` | 单元测试 | 1 个 | 主脑模板加载和配置持久化 |
| `test_run_commands.py` | 单元测试 | 2 个 | 斜杠命令解析 |
| `test_deepseek_balance.py` | 单元测试 | 1 个 | 余额查询和缓存 |
| `test_deepseek_usage.py` | 单元测试 | 1 个 | 用量记录和本地费用估算 |

### 11.2 测试基础设施

- **Fixture**：`tmp_path` 工作空间 + 从 `agents/` 目录复制示例 Agent 配置
- **Settings 注入**：测试时创建独立 `Settings(instance_dir=tmp_path)`，自动使用临时目录
- **`test_api.py`**：整合了 conftest 的 `app` 和 `client` fixture，使用真正的 SQLite 内存数据库
- **演示模式**：默认无 API Key，自动进入演示模式，验证完整 DAG 执行流程

### 11.3 覆盖分析

| 模块/组件 | 覆盖率 | 说明 |
|-----------|--------|------|
| REST 路由 | 高 | health, status, agents, skills, workspace, scheduler, brain, deepseek, runs(CRUD+SSE) 均有测试 |
| 运行生命周期 | 高 | 创建、完成、取消、删除、重试、继续、孤立运行清理 |
| LangGraph 图 | 中 | 并行分发+汇流屏障已验证，缺少 discovery 和 interrupt 流程测试 |
| DeepSeek 规划器 | 中 | Agent 路由和排除规则已验证，缺少完整规划流程测试 |
| 项目管理 | 低 | 仅有间接覆盖（通过运行测试触发） |
| 知识库 | 低 | 缺少专用测试 |
| 记忆系统 | 低 | 缺少专用测试 |
| 中断系统 | 低 | 缺少完整流程测试 |
| SSE 事件流 | 低 | 仅在运行测试中验证事件类型和顺序 |
| Agent 执行器 | 低 | 演示模式下间接覆盖 |

---

## 12. 安全与配置

### 12.1 安全设计

| 安全措施 | 实现方式 |
|----------|----------|
| 回环地址强制 | `Settings.from_env()` 中校验 `BACKEND_HOST` 仅允许 `127.0.0.1`、`localhost`、`::1` |
| API Key 保密 | 任何 API 响应不返回 Key 明文，仅返回 bool 配置状态 |
| CORS 白名单 | 仅允许前后端回环地址的跨域访问 |
| 文件路径越界防护 | `DeepSeekAgentExecutor` 的 `_build_tools` 验证所有路径在工作空间内 |
| 领域隔离 | Claude Agent SDK 的 `cwd` 和 `add_dirs` 约束文件访问范围 |
| 输入校验 | Pydantic `Field` 约束（min_length, max_length, pattern）+ `model_validator` 规则 |
| SQL 注入防御 | 全部使用参数化查询（`?` 占位符） |
| XSS 防护 | SSE 心跳使用 SSE 注释格式（`: keep-alive\n\n`）而非数据进行轮询 |

### 12.2 配置来源优先级

```
环境变量 (.env)  →  dataclass 默认值  → 运行时修改 (SQLite configs 表)
```

### 12.3 配置项完整列表

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `BACKEND_HOST` | `127.0.0.1` | 后端监听地址（强制回环） |
| `BACKEND_PORT` | `5000` | 后端监听端口 |
| `FRONTEND_PORT` | `5173` | 前端端口（CORS 来源计算） |
| `DEEPSEEK_API_KEY` | `""` | DeepSeek API 密钥 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API 端点 |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | DeepSeek 模型名 |
| `DEEPSEEK_CACHE_HIT_PRICE_USD_PER_MILLION` | `0.0028` | 缓存命中价格（百万 token） |
| `DEEPSEEK_CACHE_MISS_PRICE_USD_PER_MILLION` | `0.14` | 缓存未命中价格 |
| `DEEPSEEK_OUTPUT_PRICE_USD_PER_MILLION` | `0.28` | 输出价格 |
| `ANTHROPIC_API_KEY` | `""` | Anthropic 直连 API Key |
| `ANTHROPIC_AUTH_TOKEN` | `""` | CC Switch 管理 Token |
| `ANTHROPIC_BASE_URL` | `""` | Anthropic API 代理地址 |
| `CLAUDE_MODEL` | `claude-sonnet-4-5` | Claude 模型 |
| `MAX_CONCURRENT_AGENTS` | `3` | 最大并行 Agent 数 |
| `AGENT_MAX_TURNS` | `12` | Agent 最大交互轮次 |
| `AGENT_TIMEOUT_SECONDS` | `900` | Agent 超时秒数 |

---

## 13. 关键观察与建议

### 13.1 架构优势

1. **纯手工 DI**：没有框架绑定（无 Flask-SQLAlchemy、无 Flask-Migrate），ServiceContainer 显式管理依赖图，测试时容易 mock。
2. **异步非阻塞**：运行执行使用 daemon 线程，HTTP 请求不阻塞，SSE 流独立于请求-响应周期。
3. **演示模式**：无 API Key 时可运行完整用户界面演示，降低新用户使用门槛。
4. **配置迁移**：从旧 JSON 文件到 SQLite configs 表的平滑迁移机制（`migrate_config_from_file`）。
5. **领域模型集中**：所有数据契约定义在 `domain/` 下，路由和服务共享同一套 Pydantic 模型。
6. **安全优先**：强制回环地址、不暴露密钥、参数化查询。

### 13.2 需要关注的改进点

1. **无数据库迁移机制**：`_initialize()` 使用 `CREATE TABLE IF NOT EXISTS` + 手动 ALTER TABLE 哈希 diff，不适用于生产环境的 Schema 变更管理。建议引入 Alembic 或 Flyway 风格的迁移。

2. **ORM 缺失**：直接使用原始 SQL + `sqlite3.Row`，缺少类型安全的 ORM 层。好处是零依赖和完全控制，坏处是手写 SQL 容易出错、难以重构，且缺乏自动映射。

3. **测试覆盖缺口**：
   - 知识库 CRUD 和混合检索无专用测试
   - 记忆系统（短期/长期）无测试
   - 中断指令完整流程无测试
   - SSE 事件流无独立测试
   - 管理端 API（项目/模板/模板中心）无专用测试

4. **进程模型限制**：
   - `threaded=True` + SQLite WAL 支持并发，但单个 Python 进程受 GIL 限制
   - daemon 线程在 `run.py` 的 `app.run()` 上下文中运行，不适合 gunicorn/uWSGI 的多 worker 模式
   - 重启时遗留的 `queued`/`running` 状态靠 `recover_interrupted_runs()` 修复，属于尽力而为方案

5. **`DeepSeekExecutor` 工具实现**：`_build_tools()` 使用闭包动态创建工具函数，其中 `Read`/`Write`/`Edit`/`Glob`/`Grep`/`Bash` 全部是手写简化版，与 Claude Agent SDK 的完整工具集能力有差距。

6. **Graph 中的内存泄漏风险**：`GraphState.results` 使用 `operator.add` reducer 不断累积，长时间多轮运行可能消耗过多内存。当前每轮 wave 后 `compact_memory` 处理 Agent 消息压缩，但 results 数组本身未做裁剪。

7. **无 OpenAPI 文档**：40+ 端点全部以代码即文档方式维护，缺乏自动生成的 OpenAPI/Swagger 规范。前后端 API 变更时容易出现契约不同步。

8. **Secret 管理**：API Key 通过 `.env` 文件管理，进程内纯文本存储。建议引入更安全的密钥管理方案（如系统密钥环或加密环境变量）。

9. **去重索引问题**：`interrupt_commands` 表有两个同名索引 `idx_interrupt_run`（第 135 行和第 218-219 行）。

10. **`depends_on` 循环检测过于严格**：`TaskDag` 的 `validate_graph` 对循环依赖的检测覆盖了所有节点，但错误消息不够具体（不指明具体冲突路径）。

---

*文档结束*
