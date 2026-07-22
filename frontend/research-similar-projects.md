# 开源项目调研：AI Agent 工作流管理前端

> 调研日期：2026-07-22
> 目标：在 GitHub / GitLab 等平台搜索与当前项目（Vue 3 + TypeScript + Vite + EventSource + 工作区管理）类似的开源前端项目

## 当前项目特征摘要

- **技术栈**：Vue 3 + TypeScript + Vite，纯 Composition API + `<script setup>`
- **状态管理**：响应式 `reactive` + `computed`（无 Pinia/Vuex，自建 `useWorkspace` composable）
- **实时通信**：原生 `EventSource` (SSE)，连接 `/runs/{id}/stream?after={n}`
- **核心概念**：多 Agent 协作工作台、任务 DAG（由 DeepSeek 规划 → LangGraph 执行）、并行调度批次
- **UI 模式**：侧边栏运行历史 + 主工作区（PlanBoard DAG 卡片 + EventTimeline 时间线 + AgentInspector 面板）+ 配置中心
- **事件类型**：`run.*`, `planner.*`, `plan.*`, `agent.*`, `tool.*`, `skill.*`, `brain.*`

---

## 候选项目分析

### 1. n8n — 公平代码工作流自动化平台

| 属性 | 内容 |
|------|------|
| **仓库地址** | [https://github.com/n8n-io/n8n](https://github.com/n8n-io/n8n) |
| **Star 数** | ⭐ 197,449 |
| **主语言** | TypeScript |
| **最近更新** | 2026-07-22（持续活跃） |
| **开源协议** | Sustainable Use License（公平代码） |

**简要描述**：n8n 是一个可自托管的、带原生 AI 能力的工作流自动化平台。支持 400+ 集成、可视化构建、自定义代码节点。前端提供完整的节点编排画布（基于 Vue Flow + Dagre），用户拖拽节点连接成 DAG 定义业务逻辑。

**相似点**：
- 前端技术栈高度一致：**Vue 3** + **Pinia** + TypeScript + Vite
- 使用 `@vue-flow/core` 和 `@dagrejs/dagre` 进行 **DAG 可视化与自动布局**——与当前项目的 PlanBoard 同构
- UI 组件库使用 Element Plus，与当前项目风格接近
- 支持 AI Agent 节点（LLM 调用、工具调用），概念上类似当前项目的 Agent 分派
- 多节点并行执行与状态追踪

**差异点**：
- n8n 的 DAG 是**用户手动构建**的（拖拽式），当前项目的 DAG 由 **DeepSeek 自动规划**生成
- n8n 没有"任务时间线"和"运行批次（waves）"概念，执行颗粒度是逐个节点而非分批并行
- n8n 使用 WebSocket + REST 而非 SSE EventSource 进行实时推送
- n8n 是一个完整的后端 + 前端项目，核心业务由后端 Node.js 执行；当前项目前后端分离、调度层是 Python
- 工作区管理模型不同：n8n 是"项目/工作流"模型，当前项目是"运行（Run）/对话轮次"模型

**成熟度**：业界顶级。近 20 万 Star，企业级使用广泛，CI/CD 和文档完备。

---

### 2. Dify — AI 应用开发平台（Agentic Workflow + RAG）

| 属性 | 内容 |
|------|------|
| **仓库地址** | [https://github.com/langgenius/dify](https://github.com/langgenius/dify) |
| **Star 数** | ⭐ 149,760 |
| **主语言** | TypeScript（Web 前端） + Python（后端 API） |
| **最近更新** | 2026-07-22（持续活跃） |
| **开源协议** | Apache 2.0 |

**简要描述**：Dify 是一个 AI 应用开发平台，支持构建 Agentic 工作流、RAG 管线、丰富的 AI 模型与工具集成。提供可视化工作流编排器（基于 ReactFlow），支持多 Agent 协作和知识库管理。

**相似点**：
- 核心概念高度重合：**Agent 编排、任务工作流、LLM 规划**
- 使用 SSE / WebSocket（`socket.io-client`）进行实时流式传输——与当前项目 EventSource 模式一致
- 支持多模型切换（类似当前项目的 DeepSeek / Claude / CC-Switch 路由）
- 有知识库 / Skill 概念（对应当前项目的 Skill 配置）
- 工作流可视化含节点与连线（ReactFlow DAG）

**差异点**：
- 前端技术栈是 **React / Next.js** 而非 Vue 3（使用 `@tanstack/react-query`、TailwindCSS、ReactFlow）
- 工作流构建是**手动的**（类似 n8n 拖拽），不是由 LLM 自动生成 DAG
- 没有"运行（Run）"作为顶层概念的多轮对话模型，更接近"应用 → 对话"模式
- 缺少当前项目的"调度批次（parallel waves）"和汇流（merge junction）可视化
- 没有 DeepSeek 余额/用量面板

**成熟度**：业界顶级。近 15 万 Star，活跃社区，商业化产品（Dify Cloud）成熟运营。

---

### 3. MaxKB — 开源企业级智能体平台

| 属性 | 内容 |
|------|------|
| **仓库地址** | [https://github.com/1Panel-dev/MaxKB](https://github.com/1Panel-dev/MaxKB) |
| **Star 数** | ⭐ 22,174 |
| **主语言** | Python（后端） + Vue（前端） |
| **最近更新** | 2026-07-22（持续活跃） |
| **开源协议** | GPL 3.0 |

**简要描述**：MaxKB 是 1Panel 团队开发的开源企业级智能体平台，支持知识库构建、多模型接入、Agent 编排和应用发布。提供开箱即用的 AI 问答系统，适合企业内部知识管理与智能客服场景。

**相似点**：
- 前端使用 **Vue** 技术栈（与当前项目一致）
- 多 Agent 配置模型：支持定义 Agent 的技能、工具、知识库——对应当前项目的 Agent 编辑器
- 知识库 / Skill 管理体系——与当前项目的 Skill 配置相似
- 支持多模型（DeepSeek、OpenAI 等），与当前项目的多模型路由类似
- 同为国产开源项目，社区和生态有重叠

**差异点**：
- MaxKB 更偏 **RAG 知识库问答**，Agent 编排是其扩展功能而非核心；当前项目核心就是 Agent 任务编排
- 没有任务 DAG 可视化（PlanBoard），没有执行时间线（EventTimeline）
- 没有"调度器→规划→并行执行→汇流"的 LangGraph 执行模型
- 前端没有 SSE EventSource 实时事件流（偏向传统请求-响应）
- 没有"运行（Run）"历史管理侧边栏

**成熟度**：快速成长中。2.2 万 Star，中国开源社区活跃，企业采用案例增多。

---

### 4. Flowise — 可视化 AI Agent 构建器

| 属性 | 内容 |
|------|------|
| **仓库地址** | [https://github.com/FlowiseAI/Flowise](https://github.com/FlowiseAI/Flowise) |
| **Star 数** | ⭐ 54,832 |
| **主语言** | TypeScript |
| **最近更新** | 2026-07-22（持续活跃） |
| **开源协议** | Apache 2.0 |

**简要描述**：Flowise 是一个低代码拖拽式 AI Agent 构建工具。用户通过 ReactFlow 画布将 LLM 链、工具、记忆、向量存储等组件连接成 Agent 工作流。支持 LangChain 生态，可导出为 API 或嵌入式聊天组件。

**相似点**：
- **ReactFlow DAG 可视化**——是 AI Agent 工作流编排的标杆实现（类似当前项目的 PlanBoard 概念）
- 组件化节点设计：每个节点代表一个执行单元（LLM / Tool / Memory），有明确的输入输出类型
- 支持工具调用链路——对应当前项目的 `tool.started` 事件和工具参数展示
- TypeScript 全栈

**差异点**：
- 前端是 **React**，非 Vue 3
- 工作流由用户**手动构建**（拖拽），不是 LLM 自动规划生成
- 没有运行历史（RunSidebar）和多轮对话延续
- 没有调度器概念——Flowise 是一次性执行 DAG，不涉及 LangGraph 式的分层调度和并行分流
- 缺少实时事件流（SSE）的精细化展示（EventTimeline）
- 没有 DeepSeek 余额/用量面板

**成熟度**：成熟。5.5 万 Star，LangChain 生态核心项目，Docker 一键部署，插件市场活跃。

---

### 5. FastGPT — 知识库 + 可视化 AI 工作流编排

| 属性 | 内容 |
|------|------|
| **仓库地址** | [https://github.com/labring/FastGPT](https://github.com/labring/FastGPT) |
| **Star 数** | ⭐ 29,069 |
| **主语言** | TypeScript |
| **最近更新** | 2026-07-22（持续活跃） |
| **开源协议** | Apache 2.0 |

**简要描述**：FastGPT 是基于 LLM 的知识库平台，提供数据处理、RAG 检索、可视化 AI 工作流编排等全套能力。用户可通过拖拽式界面构建复杂问答系统，无需深度配置。

**相似点**：
- **可视化 AI 工作流编排**——拼装节点/插件来定义 Agent 行为
- 知识库 + 工具调用的组合模式——对应当前项目的 Skill + Tool
- 工作流有明确的输入/输出节点，形成隐式 DAG
- 支持多模型与多数据源

**差异点**：
- 前端是 **React / Next.js**（Chakra UI），非 Vue 3
- 核心定位是 **RAG 知识库问答**，Agent 工作流是辅助能力；当前项目核心是 Agent 任务协作
- 工作流是**人工设计的模板**，不是 LLM 自动规划生成的 DAG
- 没有执行时间线、并行批次、调度器状态等实时反馈层
- 没有 AgentInspector 式的多 Agent 实时状态面板

**成熟度**：成熟。2.9 万 Star，Sealos 生态核心项目，企业用户广泛。

---

## 综合对比矩阵

| 维度 | 当前项目 | n8n | Dify | MaxKB | Flowise | FastGPT |
|------|----------|-----|------|-------|---------|---------|
| 前端框架 | **Vue 3** | **Vue 3** ✅ | React | Vue | React | React |
| 状态管理 | reactive | Pinia | TanStack Query | — | Redux | TanStack Query |
| DAG 可视化 | 自研（CSS Grid） | Vue Flow + Dagre | ReactFlow | — | ReactFlow | 简化版 |
| 实时流 | EventSource (SSE) | WebSocket | Socket.io / SSE | — | — | — |
| 任务自动规划 | LLM 生成 | 手动拖拽 | 手动拖拽 | 模板 | 手动拖拽 | 手动/模板 |
| 并行调度层 | LangGraph waves | 无 | 无 | 无 | 无 | 无 |
| 运行历史 | RunSidebar | 执行历史 | 对话历史 | 对话历史 | — | 对话历史 |
| 多 Agent 面板 | AgentInspector | 无 | 无 | Agent 列表 | 无 | 无 |
| Token 用量 | DeepSeek 面板 | 无 | 有 | 无 | 无 | 无 |
| 工作区管理 | ✅ | 项目模式 | 应用模式 | 应用模式 | 无 | 应用模式 |
| 成熟度 | POC | ⭐197k | ⭐150k | ⭐22k | ⭐55k | ⭐29k |

## 关键发现与启示

1. **Vue 3 在 AI Agent 前端领域是少数派**：主流 AI 工作流/Agent UI 几乎全是 React（Dify、Flowise、FastGPT）。n8n 是个显著例外，其 Vue 3 + Vue Flow + Pinia 技术栈与当前项目最接近，可重点参考其 DAG 画布和节点编辑器实现。

2. **DAG 可视化成熟方案**：n8n 的 `@vue-flow/core` + `@dagrejs/dagre` 是 Vue 生态中经过验证的组合。当前项目自研的 CSS Grid PlanBoard 在节点数增多后可能需要迁移到更成熟的 DAG 布局引擎。

3. **SSE EventSource 是差异化优势**：Dify 使用 Socket.io 实现流式传输，但当前项目使用的原生 `EventSource` 更轻量。Dify 的 `streamdown` 等 Markdown 流式渲染能力值得借鉴。

4. **LLM 自动规划 DAG 是独特卖点**：以上所有候选项目的工作流都是**人工设计**的，而当前项目的 DeepSeek → Plan DAG 自动生成能力是核心竞争力。前端应当更好地展示"规划中→规划完成→任务图生成"这一过程（当前 EventTimeline 的 `planningActive` 动画已是一个好起点）。

5. **可参考的功能模块**：
   - n8n 的 Vue Flow 节点编辑器——用于未来可能的手动 DAG 调整
   - Dify 的 Prompt 编辑器（Monaco Editor）——用于增强 PromptComposer
   - Flowise 的节点连接验证和类型检查——用于 PlanBoard 的依赖关系可视化增强
   - MaxKB 的 Agent 模板和知识库管理——用于扩展 Skill 体系

## 备注

- 调研通过 GitHub REST API 获取元数据（Star、语言、更新时间），通过 `raw.githubusercontent.com` 读取各项目 `package.json` 获取前端依赖。
- GitHub 搜索以 `vue 3 AI agent workflow orchestration`、`SSE EventSource dashboard frontend`、`agent task DAG visualization` 等关键词进行多轮检索。
- 部分仓库因 API 限速未能获取完整元数据，但核心数据点（Star、技术栈、描述）已覆盖。
