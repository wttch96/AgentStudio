# Agent Studio

本机多 Agent 协作工作台。DeepSeek 主脑编排多 Agent 团队，LangGraph 调度执行，LangMem 管理分层记忆。

> 强制绑定 `127.0.0.1`，所有数据保存在本机 SQLite。

## 项目概述

- **前端**: Vue 3 + TypeScript + Vite (端口 5173)
- **后端**: Flask + LangGraph + LangChain + Claude Agent SDK (端口 5000)
- **数据库**: SQLite (WAL 模式)
- **主脑 LLM**: DeepSeek API
- **执行 Agent**: Claude Agent SDK / LangChain + DeepSeek
- **记忆系统**: LangMem + SqliteSaver

## 核心文件与目录说明

### 根目录

| 路径 | 用途 |
|------|------|
| `README.md` | 项目说明文档 (UTF-8 编码) |
| `.env` | 环境变量配置 (API Key, 端口等，不入 git) |
| `.env.example` | 环境变量模板 |
| `.gitignore` | Git 忽略规则 |
| `start.sh` / `stop.sh` | 一键启动/停止后端+前端 |
| `scripts/start-local.sh` / `scripts/stop-local.sh` | 本地启动脚本 |
| `agents/` | Agent 模板文件目录 |
| `config/` | 默认配置文件 |
| `config/brain.default.json` | 主脑编排默认提示词 |
| `config/claude-settings.cc-switch.example.json` | CC Switch 配置示例 |
| `docs/` | 技术文档目录 |
| `docs/technical-architecture.md` | 技术架构文档 |
| `docs/images/` | 文档截图 |

### 数据存储文件 (SQLite)

| 路径 | 用途 |
|------|------|
| `backend/instance/agents-manager.db` | **主数据库** - 项目、Agent、模板、知识库、记忆、配置、用量统计 |
| `backend/instance/agents-manager.db-shm` | SQLite WAL 共享内存文件 |
| `backend/instance/agents-manager.db-wal` | SQLite WAL 预写日志 |
| `.agent-studio-checkpoints.db` | **LangGraph Checkpointer 数据库** - 任务执行状态快照、checkpoint、中断恢复 |
| `.agent-studio-checkpoints.db-shm` | Checkpointer WAL 共享内存 |
| `.agent-studio-checkpoints.db-wal` | Checkpointer WAL 预写日志 |

> 两个数据库各有职责：`agents-manager.db` 存储持久化业务数据（项目配置、模板、知识库等），`.agent-studio-checkpoints.db` 存储 LangGraph 图执行的状态快照（用于中断恢复和状态重放）。

### 后端 `backend/`

| 路径 | 用途 |
|------|------|
| `backend/run.py` | Flask 应用启动入口 |
| `backend/pyproject.toml` | Python 项目配置与依赖 |
| `backend/app/__init__.py` | Flask app 工厂函数 |
| `backend/app/config.py` | 环境配置读取 (Settings dataclass)，数据库路径定义 |
| `backend/app/api/routes.py` | Flask REST API 路由 |
| `backend/app/domain/` | 领域模型 (models, configuration) |
| `backend/app/agents/` | Agent 执行器实现 |
| `backend/app/agents/__init__.py` | Agent 基类与分派逻辑 |
| `backend/app/agents/claude_executor.py` | Claude Agent 执行器 (Claude Agent SDK) |
| `backend/app/agents/deepseek_executor.py` | DeepSeek Agent 执行器 (LangChain) |
| `backend/app/agents/rag_executor.py` | RAG Agent 执行器 (知识检索) |
| `backend/app/agents/registry.py` | Agent 注册表 (按项目缓存) |
| `backend/app/agents/skill_registry.py` | Skill 注册表 |
| `backend/app/orchestration/` | LangGraph 编排 |
| `backend/app/orchestration/graph.py` | LangGraph 图定义 (含 memory 节点) |
| `backend/app/planning/` | DeepSeek DAG 编排器 |
| `backend/app/services/` | 业务服务层 |
| `backend/app/services/container.py` | 服务容器 (依赖注入) |
| `backend/app/services/project_manager.py` | 项目管理 (CRUD) |
| `backend/app/services/knowledge_store.py` | 知识库管理 (FTS5 全文搜索) |
| `backend/app/services/memory_manager.py` | 分层记忆管理 (LangMem) |
| `backend/app/services/memory_settings.py` | 记忆策略配置 |
| `backend/app/services/run_manager.py` | 任务运行管理 |
| `backend/app/services/run_commands.py` | 运行命令处理 |
| `backend/app/services/brain_settings.py` | 主脑配置管理 |
| `backend/app/services/scheduler_settings.py` | 调度配置管理 |
| `backend/app/services/workspace_settings.py` | 工作目录配置 |
| `backend/app/services/deepseek_usage.py` | DeepSeek 用量统计 |
| `backend/app/services/deepseek_balance.py` | DeepSeek 费用估算 |
| `backend/app/services/interrupt_router.py` | 中断路由 (暂停/注入引导) |
| `backend/app/storage/sqlite_store.py` | SQLite 持久化 (所有表的 CRUD) |
| `backend/app/events/` | SSE 事件流 |

### 主数据库表结构 (`agents-manager.db`)

| 表 | 用途 |
|----|------|
| `runs` | 任务运行记录 (id, objective, status, final_answer) |
| `events` | 运行事件流 (agent 消息、工具调用、token 用量) |
| `projects` | 项目配置 |
| `project_agents` | 项目下的 Agent 定义 |
| `agent_templates` | Agent 模板 (跨项目复用) |
| `skill_templates` | Skill 模板 |
| `project_skills` | 项目级 Skill |
| `knowledge_entries` / `knowledge_fts` | 知识库条目 + FTS5 全文索引 |
| `memories` / `session_summaries` | 分层记忆 (短期 + 长期) |
| `*_memory_state` | LangMem 记忆状态表 |
| `configs` | KV 配置 (主脑/记忆/调度等全局设置) |
| `deepseek_usage` | DeepSeek API 用量日志 (tokens, 费用估算) |
| `interrupt_commands` | 中断指令队列 |

### 前端 `frontend/`

| 路径 | 用途 |
|------|------|
| `frontend/src/main.ts` | Vue 应用入口 |
| `frontend/src/App.vue` | 根组件 |
| `frontend/src/types.ts` | TypeScript 类型定义 |
| `frontend/src/api/client.ts` | API 客户端 (后端通信) |
| `frontend/src/composables/useWorkspace.ts` | 工作空间状态管理 |
| `frontend/src/composables/useTheme.ts` | 主题切换 (深色模式) |
| `frontend/src/components/AppHeader.vue` | 顶部导航栏 |
| `frontend/src/components/PromptComposer.vue` | 聊天输入框 (含中断按钮) |
| `frontend/src/components/DagGraph.vue` | DAG 流程图可视化 |
| `frontend/src/components/EventTimeline.vue` | 执行时间线 |
| `frontend/src/components/ThinkingTimeline.vue` | 思考过程时间线 (折叠展开) |
| `frontend/src/components/StreamingChat.vue` | 流式对话展示 |
| `frontend/src/components/ConversationView.vue` | 对话历史视图 |
| `frontend/src/components/AgentInspector.vue` | 右侧 Agent 状态面板 + Token 统计 |
| `frontend/src/components/PlanBoard.vue` | 任务看板 |
| `frontend/src/components/ProjectDialog.vue` | 项目创建/编辑弹窗 |
| `frontend/src/components/RunSidebar.vue` | 运行侧边栏 |
| `frontend/src/components/config/` | 配置中心 7 个标签页组件 |
| `frontend/src/styles/` | 全局样式 |

### 运行时文件 `.run/`

| 路径 | 用途 |
|------|------|
| `.run/backend.pid` | 后端进程 PID |
| `.run/frontend.pid` | 前端进程 PID |
| `.run/backend.log` | 后端运行日志 |
| `.run/frontend.log` | 前端运行日志 |

### Claude Code 配置 `.claude/`

| 路径 | 用途 |
|------|------|
| `.claude/settings.local.json` | 项目级权限配置 (允许的 Bash 命令等) |
| `.claude/skills/` | 项目级 Skill 定义 |

## 数据保存位置汇总

| 数据类型 | 存储位置 | 格式 |
|----------|----------|------|
| 项目配置、Agent 定义、模板 | `backend/instance/agents-manager.db` | SQLite |
| 知识库条目 | `backend/instance/agents-manager.db` (knowledge_entries + FTS5) | SQLite |
| 分层记忆 (短期+长期) | `backend/instance/agents-manager.db` (memories + session_summaries) | SQLite |
| 任务运行历史与事件 | `backend/instance/agents-manager.db` (runs + events) | SQLite |
| DeepSeek 用量统计 | `backend/instance/agents-manager.db` (deepseek_usage) | SQLite |
| KV 配置 (主脑/记忆/调度) | `backend/instance/agents-manager.db` (configs) | SQLite |
| LangGraph 执行状态快照 | `.agent-studio-checkpoints.db` | SQLite (SqliteSaver) |
| 环境变量 / API Key | `.env` | 文本 |
| 默认配置模板 | `config/` | JSON |
| Claude Code 权限/设置 | `.claude/` | JSON / Markdown |
| 运行时 PID/日志 | `.run/` | 文本 |

## 架构

```
用户目标 → 主脑编排 (DeepSeek) → 生成 DAG
         → LangGraph 调度分发
              ├─ Claude Agent SDK (编码、文件操作)
              ├─ DeepSeek Agent / LangChain (通用编码)
              └─ RAG Agent / LangChain (知识检索录入)
         → 结果汇流 → 下一轮 (用户可随时注入引导)
              ↓
         LangMem 记忆压缩 + 长期提取 (自动)
```

## Agent 团队

| 类型 | 引擎 | 工具 | 工作目录 |
|------|------|------|----------|
| **Claude Agent** | Claude Agent SDK | Read/Write/Edit/Glob/Grep/Bash/Skill | 有 |
| **DeepSeek Agent** | LangChain + DeepSeek | 同上 | 无 |
| **RAG Agent** | LangChain + DeepSeek | search/get/add/list_knowledge | 无 |
| **主脑** | DeepSeek API | DAG 编排 | — |

## 记忆系统

| 层 | 技术 | 触发时机 |
|----|------|----------|
| **短期** | SqliteSaver + 滑动窗口压缩 | 每个 wave 后 |
| **长期** | LangMem MemoryStoreManager + ThreadExtractor | 执行完成后 |
| **策略** | StrategyEngine 配置驱动 | token/轮次/闲置阈值 |

## 常用命令

### 启动与停止
```bash
./start.sh       # 一键启动 (后端 + 前端)
./stop.sh        # 停止所有服务
```

### 访问
- 前端: `http://127.0.0.1:5173`
- 后端 API: `http://127.0.0.1:5000`

### 环境配置
```bash
cp .env.example .env   # 填入 API Key
```
必填: `DEEPSEEK_API_KEY`
可选: `ANTHROPIC_BASE_URL` (CC Switch 地址), `ANTHROPIC_API_KEY` (直连)

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST/DELETE | `/api/projects` | 项目 CRUD |
| GET/POST/PUT/DELETE | `/api/projects/{id}/agents` | 项目 Agent 管理 |
| GET/POST/PUT/DELETE | `/api/templates` | 模板管理 |
| GET/POST/PUT/DELETE | `/api/knowledge` | 知识库 |
| GET/POST/PUT | `/api/skills` | Skill 管理 |
| GET/PUT | `/api/brain` | 主脑配置 |
| POST/GET/DELETE | `/api/runs` | 任务运行 |
| POST | `/api/runs/{id}/interrupt` | 中断/注入引导 |
| GET/PUT | `/api/memory` | 记忆配置 |
| GET/PUT | `/api/scheduler` | 调度配置 |

## 技术栈

- **Python**: 3.11+, Flask, LangGraph, LangChain, LangMem, Claude Agent SDK
- **Node.js**: 20+, Vue 3, TypeScript, Vite
- **数据库**: SQLite (WAL 模式, FTS5 全文搜索)
- **LLM**: DeepSeek API (主脑+RAG+DeepSeek Agent), Claude (Claude Agent SDK via CC Switch)
