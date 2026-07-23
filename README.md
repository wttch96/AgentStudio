# Agent Studio

Agent Studio 是一个仅在本机运行的多项目软件工程 Agent 工作台。你创建项目、选择 Agent 模板，DeepSeek 主脑分析目标并生成实施 DAG，Claude Agent SDK 实现的 Coding Agent 按 DAG 并行执行编码任务，LangGraph 负责分流、调度和汇流。

> 项目强制绑定 `127.0.0.1`，配置、任务记录、Token 统计和工作目录信息都保存在本机。

## 核心概念

### 多项目管理

- 每个项目独立隔离：各自的 Coding Agent、Skill、知识库互不影响。
- 主脑（DeepSeek）为全局配置，跨项目协调规划和验收。
- 工作目录、调度参数、记忆系统为全局配置。

### 项目内的 Coding Agent

- 创建项目时从模板勾选需要的 Agent（Vue 前端、React 前端、Flask 后端、SpringBoot 后端、Netty 数据服务等）。
- 所有 Coding Agent 基于 Claude Agent SDK 实现，在配置中心的「Agent 配置」Tab 中编辑提示词、工具权限、关联 Skill 和工作子目录。
- 模板可自定义扩展（`POST /api/templates`）。

### 知识库（RAG）

- 每个项目拥有独立的知识库，支持混合检索（BM25 全文 + 向量相似度）。
- 知识条目支持分类（API、代码示例、错误处理、部署等）、标签、过期时间。
- 点赞/踩反馈自动调整知识排序权重。
- 支持知识关联关系（api_example、error_handling、dependency、related）。

### Skill

- 每个项目可拥有独立的 Skill，在配置中心的「Skill 编辑」Tab 中创建和管理。
- Skill 可关联到项目的 Coding Agent，为 Agent 提供领域知识和操作指南。

## 主要功能

### 项目发现、契约规划和并行执行

- DeepSeek 主脑分析目标后在当前项目下生成任务 DAG。
- Coding Agent 按 DAG 依赖关系并行执行——契约明确后前后端可同步编码。
- 每一批 Agent 完成后经显式 barrier 汇流，再执行下游节点。
- DeepSeek 在任务结束时读取全部执行结果并做最终验收。

### 任务流程图（DAG 可视化）

- 顶部显示任务流程图为 SVG 图结构：主脑规划 → 各任务节点 → 结果汇总。
- 节点按拓扑深度自动分层，依赖边使用贝塞尔曲线箭头连接。
- 颜色编码状态：灰=等待、蓝=执行中（脉冲动画）、绿=完成、红=失败。
- 点击节点展开详情：任务目标、Agent 名称、执行结果、耗时。
- 图例在底部显示，图容器可滚动。

### 可观察的 Agent 时间线

- 实时显示规划、分流、Agent 启动、工具调用、Skill 加载、汇流和最终输出。
- 多个 Agent 在独立泳道中并行展示。
- 页面直接展示 DeepSeek 生成的共享接口/协议契约。
- 每条 Agent 泳道可以独立折叠，折叠后保留任务标题和运行状态。
- 连续的同名工具调用自动合并，展开后仍能查看每次调用参数。
- 正在工作的 Agent 会在右侧状态栏持续闪烁，完成或失败后自动停止。
- 失败节点显示完整错误类型、摘要和执行器返回原因。

### 分层记忆系统（LangGraph Checkpointer + LangMem）

三层记忆架构：

| 层级 | 技术 | 说明 |
|------|------|------|
| **短期记忆** | LangGraph SqliteSaver | 每个图节点执行后自动 checkpoint 状态（messages + results + DAG），天然支持断点续传 |
| **长期记忆** | LangMem MemoryStoreManager | 跨会话提取重要信息、合并记忆、检索历史——项目结构认知、决策理由、Agent 能力评估、经验教训 |
| **会话摘要** | LangMem ThreadExtractor | 运行结束后自动生成结构化 Thread 摘要，供后续对话的 continuation_context 使用 |

策略引擎根据可配置参数决定何时触发压缩/归档：

- `agent_sliding_window`（默认 20）：Agent 保留最近消息条数，超出后触发 LLM 摘要压缩
- `planner_sliding_window`（默认 40）：主脑保留消息条数
- `compress_trigger_tokens`（默认 8000）：触发压缩的 token 阈值
- `max_conversation_turns`（默认 100）：最大对话轮次
- `importance_decay_rate`（默认 0.95）：记忆重要性衰减率

### 中断与重规划

- 支持在运行中发送中断指令：暂停特定 Agent、注入新引导、触发主脑重规划、中止执行。
- LangGraph `interrupt()` 在每轮调度前检查中断队列，通过 checkpoint 保证中断后可恢复。
- API：`POST /runs/{id}/interrupt` + `POST /runs/{id}/resume`

### 连续任务

选中一个已结束的历史任务后继续输入，聊天框会进入"继续"模式。新一轮会继承：

- 上游目标与最终输出。
- Claude Agent 的执行结果和失败摘要。
- 原任务使用的工作目录。
- LangMem 提取的长期记忆（跨会话项目认知）。
- LangGraph SqliteSaver checkpoint 状态。

点击左侧"新建任务"后才会创建不携带历史上下文的新对话链。

### 页面配置中心

无需手工编辑项目文件，即可在页面内管理：

| Tab | 说明 | 作用域 |
|-----|------|--------|
| 主脑配置 | DeepSeek 规划提示词和验收提示词 | 全局 |
| Agent 配置 | Coding Agent 的提示词、工具、Skill、子目录 | 项目级 |
| Skill 编辑 | 创建和管理项目 Skill | 项目级 |
| 工作目录 | 默认工作空间路径 | 全局 |
| 调度配置 | 最大并行数、递归上限、超时等 | 全局 |
| 记忆配置 | 滑动窗口、压缩阈值、衰减率等 8 项参数 | 全局 |
| 知识库 | 知识条目 CRUD、搜索、关联、评分 | 项目级 |

### DeepSeek 余额和本地用量

- 查询 DeepSeek 账户可用余额、充值余额和赠送余额。
- 本地记录本项目发起的 DeepSeek 输入、缓存命中、缓存未命中和输出 Token。
- 汇总今日、本月和本地累计用量。
- 根据 `.env` 中的单价估算美元花费，并明确标注"本地统计 · 费用估算"。

### 深色/浅色模式

- 点击顶栏主题切换按钮（☀/☽）在深色和浅色模式间切换。
- 自动检测系统偏好，偏好持久化到 localStorage。
- 所有 UI 组件完整适配：流程图、时间线、配置面板、侧栏、输入框。

### 本地任务管理

- SQLite 持久化任务、事件、对话链、DeepSeek 用量、记忆记录和中断指令。
- 支持停止活动任务、中断运行、删除终态任务记录。
- 自动清理后端重启后遗留的脏运行状态。
- 左右侧栏默认打开，可分别折叠，让中间工作区自动扩展。
- SSE 断线后按照事件序号恢复，减少重复时间线记录。

## 快速开始

需要 Python 3.11+、Node.js 20+ 和 npm。

```bash
cp .env.example .env
```

至少配置 DeepSeek；Claude 可以使用 CC Switch，也可以改为直连 Anthropic：

```dotenv
DEEPSEEK_API_KEY=your-deepseek-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# CC Switch 本地路由
ANTHROPIC_BASE_URL=http://127.0.0.1:15721
ANTHROPIC_AUTH_TOKEN=PROXY_MANAGED
ANTHROPIC_API_KEY=
```

一键启动：

```bash
./start.sh
```

浏览器访问：

```text
http://127.0.0.1:5173
```

停止服务：

```bash
./stop.sh
```

未配置模型凭据时会进入演示模式，用模拟 Agent 事件验证 DAG、并行调度、SQLite 和前端时间线，不会修改所选工作区。

## 使用流程

1. 首次使用点击「创建或选择项目」→ 新建项目，选择工作目录，勾选需要的 Coding Agent 模板。
2. 之后可通过顶部项目名称按钮随时切换或管理项目。
3. 打开「配置中心」按需调整主脑提示词、Agent 配置、Skill、知识库和调度参数。
4. 在聊天框描述目标——主脑生成 DAG，Agent 按计划执行。
5. 在流程图和时间线中观察执行过程，点击节点展开详情。
6. 任务结束后直接继续输入，基于上游输出和长期记忆开始下一轮。
7. 某个节点失败时点击「重试」按钮。

## 项目结构

```text
AgentStudio/
├── frontend/               Vue 3 + TypeScript 管理界面
│   └── src/components/
│       ├── DagGraph.vue           任务流程图（SVG DAG）
│       ├── EventTimeline.vue      执行时间线
│       ├── ProjectDialog.vue      多项目管理对话框
│       ├── AppHeader.vue          顶部导航（项目切换/配置入口）
│       └── config/                配置中心组件
│           ├── ConfigCenter.vue         配置中心容器
│           ├── BrainConfigEditor.vue    主脑配置
│           ├── AgentConfigEditor.vue    Coding Agent 配置
│           ├── SkillConfigEditor.vue    Skill 编辑
│           ├── KnowledgeConfig.vue      知识库管理
│           ├── MemoryConfig.vue         记忆系统配置
│           ├── SchedulerConfigEditor.vue 调度配置
│           └── WorkspaceConfigEditor.vue 工作目录配置
├── backend/                Flask API、LangGraph、LangMem 和 SQLite
│   └── app/
│       ├── api/routes.py              全部 REST + SSE 端点
│       ├── agents/
│       │   ├── registry.py            Agent 注册表（按项目加载）
│       │   ├── skill_registry.py      Skill 注册表（全局 + 项目级）
│       │   └── claude_executor.py     Claude Agent 执行器
│       ├── services/
│       │   ├── project_manager.py     多项目 CRUD + 模板管理
│       │   ├── knowledge_store.py     知识库 BM25 + 向量混合检索
│       │   ├── brain_settings.py      主脑配置持久化
│       │   ├── memory_manager.py      LangMem 分层记忆
│       │   └── container.py           服务容器（DI）
│       ├── orchestration/graph.py     LangGraph 图定义 + SqliteSaver
│       ├── planning/deepseek_planner.py DeepSeek DAG 规划器
│       └── storage/sqlite_store.py    SQLite 完整 Schema + 迁移
├── agents/                 内置 Agent 模板 Markdown 声明
├── config/                 Claude / CC Switch 配置示例
├── start.sh                本地一键启动
└── stop.sh                 停止本地服务
```

## 内置 Agent 模板

| 模板 | 类型 | 子目录 | 说明 |
|------|------|--------|------|
| Vue 前端 | claude | frontend | Vue 3 + TypeScript + Vite |
| React 前端 | claude | frontend | React + TypeScript + Hooks |
| Flask 后端 | claude | backend | Python Flask REST API |
| SpringBoot 后端 | claude | backend | Java SpringBoot + JPA |
| Netty 数据服务 | claude | netty | Java Netty TCP/UDP 协议处理 |

## API 概览

| 分类 | 端点 | 说明 |
|------|------|------|
| 项目 | `GET/POST/DELETE /api/projects` | 项目 CRUD |
| 项目 Agent | `GET/POST/PUT/DELETE /api/projects/{id}/agents` | 项目内 Agent 管理 |
| 模板 | `GET/POST /api/templates` | Agent 模板 |
| 知识库 | `GET/POST/PUT/DELETE /api/knowledge` | 知识条目 CRUD（支持 `?project_id=`） |
| Skill | `GET/POST/PUT /api/skills` | Skill CRUD（支持 `?project_id=`） |
| Agent | `GET /api/agents` | 项目 Agent 列表（支持 `?project_id=`） |
| 主脑 | `GET/PUT /api/brain` | 主脑提示词配置 |
| 运行 | `POST/GET/DELETE /api/runs` | 任务运行管理 |
| 中断 | `POST /api/runs/{id}/interrupt` | 中断指令 |
| 记忆 | `GET/PUT /api/memory` | 记忆系统配置 |
| 调度 | `GET/PUT /api/scheduler` | 调度参数配置 |
