# Agent Studio 前端项目分析报告

> 生成时间：2026-07-23
> 基于对 `frontend/` 源码的全面只读分析

---

## 目录

1. [项目概述](#1-项目概述)
2. [技术栈清单](#2-技术栈清单)
3. [项目结构](#3-项目结构)
4. [类型定义体系](#4-类型定义体系)
5. [API 客户端映射](#5-api-客户端映射)
6. [全局状态管理](#6-全局状态管理)
7. [组件树与数据流](#7-组件树与数据流)
8. [SSE 事件协议](#8-sse-事件协议)
9. [样式系统与主题](#9-样式系统与主题)
10. [跨项目依赖与契约](#10-跨项目依赖与契约)
11. [潜在关注点](#11-潜在关注点)

---

## 1. 项目概述

**Agent Studio 前端** (`agents-manager-frontend`) 是 Agent Studio 平台的可视化管理界面，通过 REST API 和 SSE 事件流与 Flask 后端 (`agents-manager-backend`) 通信，提供以下核心能力：

- **多 Agent 任务编排**：创建运行 → SSE 实时事件流 → DAG 可视化 → 泳道时间线 → 最终汇总
- **配置中心**：主脑提示词、Agent 配置、Skill 管理、工作目录、调度参数、记忆系统、RAG、知识库
- **项目管理**：多项目 CRUD、Agent 模板选择与绑定、项目级 Agent 增删改
- **DeepSeek 监控**：账户余额、Token 用量统计、本地费用估算
- **知识库管理**：知识条目 CRUD、搜索、分类、评分反馈

---

## 2. 技术栈清单

### 运行时依赖

| 依赖 | 版本范围 | 用途 |
|------|----------|------|
| `vue` | ^3.5.0 | 前端框架（Composition API + `<script setup>`） |
| `marked` | ^18.0.7 | Markdown 渲染（对话记录中的 Agent 消息） |
| `vite` | ^7.0.0 | 构建与开发服务器 |
| `@vitejs/plugin-vue` | ^6.0.0 | Vite Vue SFC 编译插件 |

### 开发依赖

| 依赖 | 版本范围 | 用途 |
|------|----------|------|
| `typescript` | ^5.8.0 | 类型检查 |
| `vue-tsc` | ^3.0.0 | Vue SFC 类型检查 |

### 显式未使用的技术

- **无 `vue-router`**：单页面应用，无路由切换
- **无 Pinia / Vuex**：使用 `reactive()` 全局单例代替
- **无 UI 组件库**：完全自定义 CSS（Apple 风格设计系统）
- **无 OpenAPI/Swagger 生成**：API 客户端手工维护
- **无测试框架**：`package.json` 中无测试依赖

### 开发环境

| 配置项 | 值 |
|--------|-----|
| Vite 服务器 | `http://127.0.0.1:5173` |
| API 代理 | `http://127.0.0.1:5000`（`/api` + `/health` 路径代理） |
| 代理方式 | Vite `server.proxy`（同源代理，避免跨端口 CORS 问题） |
| TypeScript 目标 | ES2022 |
| 模块解析 | Bundler mode |

---

## 3. 项目结构

```
frontend/
├── index.html                  # HTML 挂载点（<div id="app">）
├── package.json                # 依赖与脚本
├── tsconfig.json               # TypeScript 项目引用
├── tsconfig.app.json           # 应用编译配置（src/）
├── vite.config.ts              # Vite 配置（host/port/proxy）
│
├── docs/                       # 文档目录（新增）
│
└── src/
    ├── main.ts                 # 应用入口（createApp + mount）
    ├── types.ts                # 全局类型定义（270 行）
    ├── vite-env.d.ts           # Vite 环境类型声明
    │
    ├── api/
    │   └── client.ts           # REST API 客户端（173 行）
    │
    ├── composables/
    │   ├── useWorkspace.ts     # 全局响应式状态 + SSE 管理（272 行）
    │   └── useTheme.ts         # 深色/浅色主题切换（25 行）
    │
    ├── components/
    │   ├── App.vue             # 根组件（三栏布局编排）
    │   ├── AppHeader.vue       # 顶栏：品牌/面板折叠/主题/项目/配置
    │   ├── RunSidebar.vue      # 左侧栏：运行历史列表
    │   ├── AgentInspector.vue  # 右侧面板：Agent 状态/余额/用量
    │   ├── DagGraph.vue        # SVG DAG 任务流程图
    │   ├── EventTimeline.vue   # 执行时间线（分流/泳道/汇流）
    │   ├── ConversationView.vue# 对话记录（Markdown 渲染）
    │   ├── PlanBoard.vue       # 任务 DAG 卡片网格
    │   ├── PromptComposer.vue  # 底部输入框（命令菜单）
    │   ├── ProjectDialog.vue   # 项目管理对话框
    │   └── config/
    │       ├── ConfigCenter.vue      # 配置中心容器（7 个 Tab）
    │       ├── BrainConfigEditor.vue # 主脑提示词编辑
    │       ├── AgentConfigEditor.vue # Agent 编辑器（工具/技能/提示词）
    │       ├── SkillConfigEditor.vue # Skill CRUD 编辑器
    │       ├── RAGConfigEditor.vue   # RAG Agent 编辑
    │       ├── WorkspaceConfigEditor.vue # 工作目录选择器
    │       ├── SchedulerConfigEditor.vue # 调度参数配置
    │       ├── MemoryConfig.vue      # 记忆系统配置
    │       └── KnowledgeConfig.vue   # 知识库 CRUD + 搜索
    │
    └── styles/
        ├── main.css            # 全局样式（505 行，含深色/浅色主题）
        └── config.css          # 配置中心样式（127 行）
```

---

## 4. 类型定义体系

文件：`src/types.ts`（270 行，14 个接口 + 1 个枚举类型）

### 4.1 运行模型

```typescript
type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'

interface Run {
  id: string
  objective: string
  workspace_root: string | null
  parent_run_id: string | null       // 延续运行的上游 ID
  conversation_id: string
  turn_index: number
  status: RunStatus
  final_answer: string | null
  error: string | null
  created_at: string
  updated_at: string
}

interface RunEvent {
  run_id: string
  sequence: number                    // 单调递增序号，用于去重
  type: string                        // 事件类型字符串
  timestamp: string
  agent_id: string | null
  task_id: string | null
  payload: Record<string, unknown>    // 灵活负载
}
```

### 4.2 Agent 模型

```typescript
interface AgentProfile {
  id: string; name: string; display_name?: string
  description: string; tools: string[]; skills: string[]
  skill_count: number; builtin: boolean; sub_dir?: string
  project_id?: string; agent_type?: 'claude' | 'deepseek' | 'rag'
}

interface AgentDetail extends AgentProfile {
  prompt: string                      // 系统提示词（仅详情时返回）
}
```

### 4.3 领域模型分类

| 类别 | 接口 | 说明 |
|------|------|------|
| **系统** | `SystemStatus` | 运行状态、模型配置、工作目录 |
| **Skill** | `SkillProfile` | Skill 名称/描述/内容 |
| **调度** | `SchedulerConfiguration` | 并行数/递归上限/轮次/超时 |
| **主脑** | `BrainConfiguration` | 规划提示词 + 验收提示词 |
| **DeepSeek** | `DeepSeekBalance`, `DeepSeekUsage`, `DeepSeekUsagePeriod` | 余额 + 用量统计 |
| **计划** | `PlanTask`, `AgentResult` | 任务 DAG 节点 + 执行结果 |
| **记忆** | `MemoryRecord`, `MemoryConfiguration`, `MemoryStats` | 记忆条目/配置/统计 |
| **中断** | `InterruptCommand` | 运行时干预指令 |
| **知识库** | `KnowledgeEntry`, `KnowledgeRelation`, `KnowledgeStats` | 知识条目/关系/统计 |
| **项目** | `Project`, `ProjectAgent` | 多项目管理 |
| **模板** | `AgentTemplate`, `SkillTemplate` | Agent/Skill 模板 |

### 4.4 设计特点

- `RunEvent.payload` 使用 `Record<string, unknown>`，灵活但缺乏编译期类型安全，消费端需要运行时类型判断
- 多处使用内联 `import("../types").Xxx` 延迟类型引用（特别是在 `api/client.ts` 中），替代顶部批量 import
- `AgentResult.status` 使用字面量联合类型 `'completed' | 'failed' | 'cancelled' | 'skipped'`，与 `RunStatus` 独立定义

---

## 5. API 客户端映射

文件：`src/api/client.ts`（173 行）

### 5.1 架构

```typescript
const API_BASE = import.meta.env.VITE_API_BASE ?? '/api'  // 默认走 Vite 代理

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // 通用 JSON fetch 封装：自动设置 Content-Type、解析错误消息
}

export const api = { /* ~40 个方法 */ }
```

### 5.2 端点全覆盖

| 分类 | 方法 | API 端点 | 后端路由 |
|------|------|----------|----------|
| 系统 | `api.status()` | `GET /status` | `/api/status` |
| Agent | `api.agents()` | `GET /agents` | `/api/agents` |
| | `api.agent()` | `GET /agents/{name}` | `/api/agents/<name>` |
| | `api.updateAgent()` | `PUT /agents/{name}` | `/api/agents/<name>` |
| Skill | `api.skills()` | `GET /skills` | `/api/skills` |
| | `api.skill()` | `GET /skills/{name}` | `/api/skills/<name>` |
| | `api.createSkill()` | `POST /skills` | `/api/skills` |
| | `api.updateSkill()` | `PUT /skills/{name}` | `/api/skills/<name>` |
| 运行 | `api.runs()` | `GET /runs` | `/api/runs` |
| | `api.run()` | `GET /runs/{id}` | `/api/runs/<id>` |
| | `api.createRun()` | `POST /runs` | `/api/runs` |
| | `api.deleteRun()` | `DELETE /runs/{id}` | `/api/runs/<id>` |
| | `api.cancelRun()` | `POST /runs/{id}/cancel` | `/api/runs/<id>/cancel` |
| SSE | `api.streamUrl()` | `GET /runs/{id}/stream` | `GET /api/runs/<id>/stream` |
| 工作目录 | `api.workspace()` | `GET /workspace` | `/api/workspace` |
| | `api.updateWorkspace()` | `PUT /workspace` | `/api/workspace` |
| | `api.browseWorkspace()` | `GET /workspace/directories` | `/api/workspace/directories` |
| 调度 | `api.scheduler()` | `GET /scheduler` | `/api/scheduler` |
| | `api.updateScheduler()` | `PUT /scheduler` | `/api/scheduler` |
| 主脑 | `api.brain()` | `GET /brain` | `/api/brain` |
| | `api.defaultBrain()` | `GET /brain/default` | `/api/brain/default` |
| | `api.updateBrain()` | `PUT /brain` | `/api/brain` |
| DeepSeek | `api.deepseekBalance()` | `GET /deepseek/balance` | `/api/deepseek/balance` |
| | `api.deepseekUsage()` | `GET /deepseek/usage` | `/api/deepseek/usage` |
| 记忆 | `api.memoryConfig()` | `GET /memory` | `/api/memory` |
| | `api.updateMemoryConfig()` | `PUT /memory` | `/api/memory` |
| 中断 | `api.interruptRun()` | `POST /runs/{id}/interrupt` | `/api/runs/<id>/interrupt` |
| | `api.resumeRun()` | `POST /runs/{id}/resume` | `/api/runs/<id>/resume` |
| 知识库 | `api.knowledgeSearch()` | `GET /knowledge` | `/api/knowledge` |
| | `api.knowledgeGet()` | `GET /knowledge/{id}` | `/api/knowledge/<id>` |
| | `api.knowledgeCreate()` | `POST /knowledge` | `/api/knowledge` |
| | `api.knowledgeUpdate()` | `PUT /knowledge/{id}` | `/api/knowledge/<id>` |
| | `api.knowledgeDelete()` | `DELETE /knowledge/{id}` | `/api/knowledge/<id>` |
| | `api.knowledgeFeedback()` | `POST /knowledge/{id}/feedback` | `/api/knowledge/<id>/feedback` |
| | `api.knowledgeRelations()` | `GET /knowledge/{id}/relations` | `/api/knowledge/<id>/relations` |
| | `api.knowledgeAddRelation()` | `POST /knowledge/relations` | `/api/knowledge/relations` |
| | `api.knowledgeStats()` | `GET /knowledge-stats` | `/api/knowledge-stats` |
| 项目 | `api.projects()` | `GET /projects` | `/api/projects` |
| | `api.createProject()` | `POST /projects` | `/api/projects` |
| | `api.deleteProject()` | `DELETE /projects/{id}` | `/api/projects/<id>` |
| | `api.projectAgents()` | `GET /projects/{id}/agents` | `/api/projects/<id>/agents` |
| | `api.addProjectAgent()` | `POST /projects/{id}/agents` | `/api/projects/<id>/agents` |
| | `api.updateProjectAgent()` | `PUT /projects/{id}/agents/{aid}` | `/api/projects/<id>/agents/<aid>` |
| | `api.deleteProjectAgent()` | `DELETE /projects/{id}/agents/{aid}` | `/api/projects/<id>/agents/<aid>` |
| 模板 | `api.templates()` | `GET /templates` | `/api/templates` |
| | `api.createTemplate()` | `POST /templates` | `/api/templates` |
| | `api.updateTemplate()` | `PUT /templates/{id}` | `/api/templates/<id>` |
| | `api.deleteTemplate()` | `DELETE /templates/{id}` | `/api/templates/<id>` |
| 模板中心 | `api.templateCenter()` | `GET /template-center` | `/api/template-center` |
| | `api.publishSkillTemplate()` | `POST /template-center/skills` | `/api/template-center/skills` |

### 5.3 设计特点

- **内联类型引用**：`knowledgeSearch`、`knowledgeGet` 等使用 `import("../types").KnowledgeEntry` 内联类型标注，而非顶部 import
- **错误处理**：`request()` 工具函数自动解析错误 JSON 体，以 `body.error ?? statusText` 抛出
- **DELETE 特殊处理**：`deleteRun`、`knowledgeDelete`、`deleteProject` 等不使用 `request<T>()`，改用原生 `fetch` 手动处理错误
- **`streamUrl`**：不发起请求，仅生成 SSE `EventSource` URL

---

## 6. 全局状态管理

文件：`src/composables/useWorkspace.ts`（272 行）

### 6.1 架构

使用 Vue `reactive()` 创建模块级单例 `state`，在 `useWorkspace()` 中暴露响应式状态和方法。组件通过 `const workspace = useWorkspace()` 共享同一实例。

```typescript
interface WorkspaceState {
  runs: Run[]                    // 运行历史
  activeRun: Run | null          // 当前选中的运行
  events: RunEvent[]             // 当前运行的事件数组（已去重 + 排序）
  projectId: string              // 当前选择的项目 ID
  projectName: string
  agents: AgentProfile[]
  skills: SkillProfile[]
  status: SystemStatus | null
  deepseekBalance: DeepSeekBalance | null
  deepseekUsage: DeepSeekUsage | null
  balanceLoading: boolean
  loading: boolean               // 初始化中
  submitting: boolean            // 正在创建运行
  error: string                  // 错误消息
}
```

### 6.2 方法一览

| 方法 | 功能 | 数据流 |
|------|------|--------|
| `initialize()` | 启动时一次性加载：status + agents + skills + runs → 自动选中最新 run → 刷新余额/用量 | `api.status()`, `api.agents()`, `api.skills()`, `api.runs()` |
| `refreshConfiguration()` | 后台刷新 agents/skills/status | `api.agents()`, `api.skills()`, `api.status()` |
| `selectRun(runId)` | 选中某次运行：关闭旧 SSE → GET 详情 → 去重 events → 若运行中则开 SSE | `api.run()` |
| `createRun(objective)` | 创建新运行：POST → 插入列表开头 → 自动选中 → 开 SSE | `api.createRun()` |
| `beginNewRun()` | 清空当前运行（切换到欢迎界面） | — |
| `cancelActiveRun()` | 取消当前运行 | `api.cancelRun()` |
| `deleteRun(runId)` | 删除运行记录 | `api.deleteRun()` |
| `refreshDeepSeekBalance()` | 刷新余额 | `api.deepseekBalance()` |
| `refreshDeepSeekUsage()` | 刷新用量 | `api.deepseekUsage()` |

### 6.3 计算属性

| 属性 | 类型 | 功能 |
|------|------|------|
| `plan` | `ComputedRef<PlanTask[]>` | 从最新 `plan.created` 事件的 `payload.tasks` 提取任务数组 |
| `planContract` | `ComputedRef<string>` | 从最新 `plan.created` 事件的 `payload.coordination_contract` 提取契约文本 |
| `agentEvents` | `ComputedRef<RunEvent[]>` | 过滤出所有 `agent_id` 不为 null 的事件 |
| `isRunning` | `ComputedRef<boolean>` | 判断 activeRun 状态是否为 `queued` 或 `running` |

### 6.4 SSE 管理

```typescript
let eventSource: EventSource | null = null

function openStream(runId: string) {
  closeStream()
  const after = state.events.at(-1)?.sequence ?? 0
  eventSource = new EventSource(api.streamUrl(runId, after))
  eventSource.addEventListener('run-event', (message) => {
    const event = JSON.parse(...)
    if (!state.events.some(item => item.sequence === event.sequence))
      state.events.push(event)       // 按 sequence 去重
    applyTerminalEvent(event)         // 处理终端状态
  })
  eventSource.onerror = () => refreshActiveRun()  // 重连时同步 REST
}

function closeStream() {
  eventSource?.close()
  eventSource = null
}
```

关键行为：
- **服务端事件名为 `run-event`**（非标准 `message` 事件）
- **`after` 参数**：从最后一个已知 sequence 开始接收（断线恢复）
- **去重逻辑**：`sequence` 字段作为唯一键
- **终端事件处理**：`applyTerminalEvent()` 识别 `run.completed` / `run.failed` / `run.cancelled` 自动关闭连接并更新状态
- **主动同步**：`refreshActiveRun()` 在 SSE 断线时通过 REST API 同步最新数据

### 6.5 延续运行（Continuation）

```typescript
// App.vue 中判断
const isContinuation = computed(() => {
  const run = workspace.state.activeRun
  return Boolean(run && ['completed', 'failed', 'cancelled'].includes(run.status))
})

// createRun 中使用
const parentRunId =
  state.activeRun && ['completed', 'failed', 'cancelled'].includes(state.activeRun.status)
    ? state.activeRun.id
    : undefined
const run = await api.createRun(objective, parentRunId)
```

---

## 7. 组件树与数据流

### 7.1 组件层次

```
App.vue
├── AppHeader.vue
│   └── useTheme()                    # 主题切换
├── RunSidebar.vue
│   └── props: runs, activeId
├── <main class="workspace">
│   ├── DagGraph.vue                  # SVG 流程图
│   │   └── props: tasks, contract, events
│   ├── EventTimeline.vue             # 执行时间线
│   │   └── props: tasks, events
│   ├── section.final-answer          # 最终汇总（内联）
│   │   └── {{ activeRun.final_answer }}
│   └── PromptComposer.vue
│       └── emits: submit(objective)
├── AgentInspector.vue
│   └── props: agents, events, deepseekBalance, deepseekUsage
├── ConfigCenter.vue (条件渲染)
│   ├── BrainConfigEditor.vue
│   ├── RAGConfigEditor.vue
│   ├── AgentConfigEditor.vue
│   ├── SkillConfigEditor.vue
│   ├── WorkspaceConfigEditor.vue
│   ├── SchedulerConfigEditor.vue
│   └── MemoryConfig.vue
└── ProjectDialog.vue (条件渲染)
```

### 7.2 组件详解

#### 7.2.1 AppHeader.vue
| 特性 | 说明 |
|------|------|
| **Props** | `status`, `leftPanelOpen`, `rightPanelOpen`, `projectName` |
| **Emits** | `configure`, `toggleLeft`, `toggleRight`, `switchProject` |
| **内部** | 集成 `useTheme()` 管理主题切换 |
| **UI 元素** | 品牌标志(A)、标题、面板折叠按钮、主题切换(☀/☽)、项目管理、配置中心按钮、连接状态芯片、本地仅芯片 |

#### 7.2.2 RunSidebar.vue
| 特性 | 说明 |
|------|------|
| **Props** | `runs: Run[]`, `activeId?: string` |
| **Emits** | `select(id)`, `create()`, `delete(id)` |
| **功能** | 新建任务按钮、运行历史列表（状态指示灯 + 目标文字 + 相对时间 + 回合徽章）、删除按钮（confirm 确认） |

#### 7.2.3 AgentInspector.vue
| 特性 | 说明 |
|------|------|
| **Props** | `agents`, `events`, `deepseekBalance`, `deepseekUsage`, `balanceLoading` |
| **Emits** | `refreshBalance` |
| **功能** | Agent 卡片列表（状态/技能/工具调用次数）、系统 Agent 面板（主脑/RAG/记忆状态）、DeepSeek 余额与用量面板 |

#### 7.2.4 DagGraph.vue
| 特性 | 说明 |
|------|------|
| **Props** | `tasks: PlanTask[]`, `events: RunEvent[]`, `contract: string` |
| **功能** | SVG 拓扑布局：从左到右渲染（主脑规划 → 任务节点按依赖层级 → 结果汇总） |
| **布局算法** | 拓扑排序计算每层深度，贝塞尔曲线连接依赖边，响应式 viewBox |
| **交互** | 点击任务节点展开详情（目标 + 结果摘要） |
| **特殊节点** | `__start__`（主脑规划）、`__end__`（结果汇总） |

#### 7.2.5 EventTimeline.vue
| 特性 | 说明 |
|------|------|
| **Props** | `tasks: PlanTask[]`, `events: RunEvent[]` |
| **核心** | 组件中最复杂的消费逻辑（~500 行） |
| **时间线分段** | 开始事件(`startEvents`) → 决策事件(`decisionEvents`) → 并行波次 → 结束事件(`finishEvents`) |
| **波次计算** | `waves` computed：基于 `PlanTask.depends_on` 的拓扑分层，相同 level 的任务同属一波 |
| **泳道渲染** | 每个 wave 中并行渲染 `agent-lanes`，支持折叠/展开单泳道或整波 |
| **工具调用折叠** | 相邻同名 `tool.started` 事件自动合并为 `调用 {tool} ×N` |
| **失败分类** | `failureCategory()`：推断失败原因类别（轮次耗尽/超时/权限/鉴权/执行错误） |

#### 7.2.6 ConversationView.vue
| 特性 | 说明 |
|------|------|
| **Props** | `events: RunEvent[]`, `finalAnswer: string | null` |
| **事件过滤** | 维护白名单事件类型列表（~26 种），支持 `interrupt.*` 事件 |
| **渲染** | `agent.message` 事件通过 `marked` 渲染 Markdown；`tool.started` 展示 JSON 参数 |
| **颜色编码** | 每种事件类型有独立的左边框颜色（event-run: 靛蓝, event-plan: 紫色, event-error: 红色 等） |

#### 7.2.7 PlanBoard.vue
| 特性 | 说明 |
|------|------|
| **Props** | `tasks`, `events`, `canRetry`, `contract` |
| **功能** | 卡片网格展示所有任务节点（状态/耗时/依赖/重试按钮） |

#### 7.2.8 PromptComposer.vue
| 特性 | 说明 |
|------|------|
| **Props** | `submitting`, `continuing`, `disabled` |
| **Emits** | `submit(objective)` |
| **功能** | 自动调整高度 textarea、快捷键提示、动态 `/brain` 与 `/<agent-name>` 引导菜单 |

#### 7.2.9 ProjectDialog.vue
| 特性 | 说明 |
|------|------|
| **Props** | `projects: Project[]` |
| **Emits** | `created(project)`, `close()` |
| **三视图** | 项目列表、新建项目（含目录浏览器 + Agent 模板多选）、项目详情（Agent 管理） |

### 7.3 配置中心组件

`ConfigCenter.vue` 为容器，7 个 Tab 切换：

| Tab | 组件 | 后端交互 |
|-----|------|----------|
| 主脑 | `BrainConfigEditor.vue` | `GET/PUT /api/brain` + `GET /api/brain/default` |
| RAG | `RAGConfigEditor.vue` | `GET agent detail` + `PUT /api/projects/{id}/agents/{id}` |
| Agent | `AgentConfigEditor.vue` | `GET agents` + `PUT project agents` + `POST add agent` + `DELETE agent` |
| Skill | `SkillConfigEditor.vue` | `GET/POST/PUT /api/skills` |
| 工作目录 | `WorkspaceConfigEditor.vue` | `GET /api/workspace` + `GET /api/workspace/directories` |
| 调度 | `SchedulerConfigEditor.vue` | `GET/PUT /api/scheduler` |
| 记忆 | `MemoryConfig.vue` | `GET/PUT /api/memory` |

### 7.4 数据流总结

```
用户输入目标
    ↓
PromptComposer @submit
    ↓
App.vue → workspace.createRun(objective)
    ↓
POST /api/runs → Run created (status: queued)
    ↓
EventSource → SSE /api/runs/{id}/stream?after=N
    ↓
[run.started] → status → 'running'
[plan.created] → plan.value + planContract.value (computed)
[wave.started] → DagGraph 新节点
[agent.started/message/tool.started] → EventTimeline 泳道事件
[agent.completed/failed] → PlanBoard / AgentInspector 状态更新
[brain.synthesizing] → main brain validation
[run.completed/failed/cancelled] → closeStream()
    ↓
final_answer → 最终汇总渲染
```

---

## 8. SSE 事件协议

### 8.1 传输层

| 项 | 值 |
|----|-----|
| 端点 | `GET /api/runs/{id}/stream?after={sequence}` |
| 事件名 | `run-event`（非标准 `message`） |
| 心跳 | 后端每 3 秒发送 `: keep-alive\n\n` |
| 传输格式 | EventSource / text/event-stream |
| 重连 | 浏览器 `EventSource` 自动重连，前端 `onerror` 额外触发 REST 同步 |

### 8.2 事件类型全集

综合 `EventTimeline.vue` 和 `ConversationView.vue` 两个消费者的过滤逻辑，前端已知的事件类型：

| 类别 | 事件类型 | EventTimeline | ConversationView | 说明 |
|------|----------|:---:|:---:|------|
| **运行生命周期** | `run.started` | ✓ | ✓ | 运行已启动 |
| | `run.completed` | ✓ | ✓ | 运行正常完成 |
| | `run.failed` | ✓ | ✓ | 运行失败 |
| | `run.cancelled` | ✓ | ✓ | 运行被取消 |
| | `run.cancel_requested` | ✓ | ✗ | 取消请求已发出 |
| | `run.summary` | ✗ | ✓ | 运行汇总 |
| **规划阶段** | `planner.started` | ✓ | ✓ | DeepSeek 正在规划（EventTimeline 含运行时间动画） |
| | `planner.bypassed` | ✓ | ✓ | 跳过规划，直接执行指定 Agent |
| | `plan.created` | ✓ | ✓ | DAG 计划已生成（含 `tasks`、`coordination_contract`、`stage`） |
| | `brain.contract_created` | ✓ | ✓ | DeepSeek 已生成共享契约 |
| | `brain.synthesizing` | ✓ | ✓ | DeepSeek 主脑正在验收 |
| **Agent 执行** | `agent.started` | ✓ | ✓ | Agent 已启动 |
| | `agent.message` | ✓ | ✓ | Agent 消息（Markdown 渲染） |
| | `agent.completed` | ✓ | ✓ | 节点已完成 |
| | `agent.failed` | ✓ | ✓ | 节点执行失败（含 `payload.error`） |
| | `agent.usage` | ✗ | ✓ | Agent 用量统计 |
| **工具调用** | `tool.started` | ✓ | ✓ | 工具调用（EventTimeline 支持同名调用折叠） |
| | `skill.loaded` | ✓ | ✓ | 加载 Skill |
| **调度波次** | `wave.started` | ✗ | ✓ | 调度波次开始 |
| | `wave.completed` | ✗ | ✓ | 调度波次完成 |
| **工作空间** | `workspace.discovery_started` | ✓ | ✓ | 工作空间发现启动 |
| **中断机制** | `interrupt.requested` | ✗ | ✓ | 中断请求发出 |
| | `interrupt.received` | ✗ | ✓ | 中断被接收 |
| | `interrupt.resolved` | ✗ | ✓ | 中断已处理 |
| **记忆系统** | `memory.compacted` | ✗ | ✓ | 记忆压缩（AgentInspector 统计） |
| | `memory.extracted` | ✗ | ✓ | 记忆提取（AgentInspector 统计） |

### 8.3 事件消费差异

两个主要消费者对事件的过滤逻辑不同：

- **EventTimeline.vue**：维护 `agentEventTypes` 集合（6 种 Agent 级别事件），按 `agent_id` 分配到泳道。总览类事件按时间线位置分类到 `startEvents` / `decisionEvents` / `finishEvents`
- **ConversationView.vue**：维护白名单列表（~26 种），统一按时间顺序渲染，每种事件有独立的图标和 CSS 类

### 8.4 plan.created 事件关键字段

```typescript
payload: {
  tasks: PlanTask[]          // 任务数组
  coordination_contract: string  // 共享接口/协议契约
  stage: 'discovery' | 'execution'  // 计划阶段
}
```

`stage` 字段用于区分发现阶段和实施阶段。`EventTimeline` 根据 `stage` 决定 `plan.created` 出现在 `startEvents` 还是 `decisionEvents`。

---

## 9. 样式系统与主题

### 9.1 CSS 变量体系

`src/styles/main.css` 定义了完善的 CSS 变量系统：

```css
:root {  /* 深色主题（默认） */
  --bg: #000;
  --sidebar: rgba(28, 28, 30, .82);
  --surface: #1c1c1c;
  --label: #f5f5f7;
  --secondary: rgba(235, 235, 245, .6);
  --blue: #0a84ff;
  --green: #30d158;
  --orange: #ff9f0a;
  --red: #ff453a;
  /* ... */
}

[data-theme="light"] {  /* 浅色主题覆盖 */
  --bg: #ffffff;
  --surface: #f5f5f7;
  --label: #1d1d1f;
  --blue: #0071e3;
  /* ... */
}
```

### 9.2 主题切换机制

```
useTheme.ts
├── localStorage 持久化（key: 'agent-studio-theme'）
├── 系统偏好检测（prefers-color-scheme: dark）
├── apply(theme): document.documentElement.setAttribute('data-theme', theme)
└── toggle(): 切换并返回新主题
```

AppHeader.vue 中调用 `useTheme()` 并实现在顶栏显示 ☀/☽ 切换按钮。

### 9.3 布局系统

```css
.app-shell {
  display: grid;
  grid-template-columns: var(--sidebar-width) minmax(0, 1fr) var(--inspector-width);
  grid-template-rows: 58px calc(100vh - 58px);
}
--sidebar-width: clamp(252px, 15vw, 320px)
--inspector-width: clamp(300px, 17vw, 350px)
--content-width: clamp(940px, 56vw, 1180px)
```

- 响应式断点：1050px（隐藏右侧面板）、720px（隐藏左侧栏，堆叠布局）
- 字号使用 `clamp(18px, calc(16px + .22vw), 24px)` 适应不同分辨率
- 毛玻璃效果广泛使用：`backdrop-filter: saturate(180%) blur(28px)`

### 9.4 设计风格

- **Apple 风格**：SF Pro 字体族、圆角矩形（8px-14px）、毛玻璃背景、柔和阴影
- **颜色语义**：蓝色=运行中/主脑/交互、绿色=完成/成功、橙色=警告/取消、红色=失败/错误
- **动画**：Agent 工作脉冲动画、规划进度条动画、运行状态呼吸灯

---

## 10. 跨项目依赖与契约

### 10.1 API 契约对齐

前端 `src/types.ts`（14 个接口）与后端 Pydantic 模型一一对应。新增端点或 payload 变更需要同步修改：

1. `types.ts`：新增/修改接口定义
2. `api/client.ts`：新增/修改 API 方法
3. 消费组件：适配新数据格式

### 10.2 SSE 事件格式协议

- 新增事件类型需同步以下内容：
  - `EventTimeline.vue` 的 `title()` / `detail()` 映射表
  - `ConversationView.vue` 的 `typeLabel()` / `typeIcon()` / `typeCssClass()` 映射表
  - `useWorkspace.ts` 的 `applyTerminalEvent()`（如果是终端事件）

- `plan.created` 事件是核心接口：
  - `payload.tasks` 被 `DagGraph`, `EventTimeline`, `PlanBoard`, `useWorkspace.plan` 四个位置消费
  - `payload.coordination_contract` 被 `DagGraph` 和 `PlanBoard` 展示
  - `payload.stage` 决定 `EventTimeline` 中的展示位置

### 10.3 运行生命周期状态机

```
queued → running → completed
                → failed
                → cancelled
     → (直接 cancelled，若尚未启动)
```

关键状态转换点：
- `useWorkspace.applyTerminalEvent()`：通过 SSE 事件实时更新 `activeRun.status`
- `useWorkspace.refreshActiveRun()`：SSE 断线时通过 REST 同步状态
- `App.vue` 的 `isContinuation`：终端状态（`completed/failed/cancelled`）触发延续模式

### 10.4 项目级 Agent 配置

项目-模板-Agent 三层关系：
```
Project
  ├─ ProjectAgent (agent_type: claude | deepseek | rag)
  │   ├─ tools, skills, sub_dir, system_prompt
  │   └─ created from AgentTemplate
  └─ AgentTemplate (category, default_prompt, default_tools, default_skills)
```

---

## 11. 潜在关注点

### 11.1 类型安全

1. **`RunEvent.payload` 类型不安全**：`Record<string, unknown>` 导致消费端需要大量运行时类型判断和强制转化。建议对已知事件 payload 定义联合类型或 discriminated union。

2. **内联类型引用分散**：`api/client.ts` 中多处使用 `import("../types").Xxx` 的内联形式，风格不统一，重构时容易遗漏。

### 11.2 SSE 事件管理

1. **两套独立的事件过滤逻辑**：`EventTimeline` 和 `ConversationView` 各有自己的事件类型白名单和映射表，新增事件类型需要同时修改两处。建议提取共享的事件类型配置模块。

2. **无 SSE 重连背压**：`EventSource.onerror` 直接调用 `refreshActiveRun()` REST 同步，无退避策略。后端短暂故障可能导致频繁 REST 轮询。

### 11.3 状态管理

1. **全局 mutable state**：使用 `reactive()` 单例意味着任何组件的修改都会影响全局。虽然当前架构简单有效，但随着功能增加可能引入难以追踪的副作用。

2. **`eventSource` 模块级变量**：不在 `state` 中，重置测试或 HMR 热替换时需要小心。

### 11.4 配置与耦合

1. **Vite 代理和后端 CORS 耦合**：Vite config 中的 `proxy` 和后端 `config.py` 中的 CORS origins 使用相同的 `127.0.0.1:5000`。配置变更需两端同步。

2. **`.env` 共享**：`BACKEND_HOST/PORT`、`FRONTEND_HOST/PORT` 前后端共享，但前端实际通过 Vite 代理而非直接连接后端。

### 11.5 测试缺失

`package.json` 无测试依赖，项目中无测试文件。核心逻辑（`useWorkspace` 状态机、`EventTimeline` 波次计算、DagGraph 布局算法）缺少单元测试和组件测试。

### 11.6 启动脚本耦合

`scripts/start-local.sh` 同时管理后端 Flask 和前端 Vite 进程。`frontend/` 不应直接依赖 `backend/` 目录的存在，但在 `vite.config.ts` 中通过 proxy 隐式依赖后端运行。
