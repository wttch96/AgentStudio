# Agent Studio 类似开源项目调研报告

> 调研日期：2026-07-22
> 调研范围：GitHub 公开仓库
> 当前项目技术栈：Flask + LangGraph + DeepSeek + Claude Agent SDK + SQLite + SSE 事件驱动

---

## 摘要

针对 Agent Studio（后称"本项目"）的核心特征——LangGraph 图编排、DeepSeek 主脑生成 DAG、Claude Agent SDK 并行执行、Flask REST/SSE 事件推送、SQLite 持久化——在 GitHub 上搜索了类似的开源项目。以下列出 5 个最具参考价值的候选项目。

---

## 候选项目 1：Mentis

| 属性 | 内容 |
|------|------|
| **名称** | Mentis |
| **仓库地址** | [https://github.com/foreveryh/mentis](https://github.com/foreveryh/mentis) |
| **简要描述** | 基于 LangGraph 构建的强大多 Agent 编排框架（multi-agent orchestration framework） |
| **主语言** | Python |
| **Star 数** | ★299 |
| **最近更新** | 2026-07-17（活跃维护中） |
| **许可证** | 未指定 |

### 与本项目的相似点

1. **LangGraph 图编排**：两者都以 LangGraph 作为核心执行引擎，构建 StateGraph 并利用 Send 分发并行任务。
2. **多 Agent 协作**：Mentis 定位为 multi-agent orchestration，与本项目的 DeepSeek 主脑 + 三个 Claude Agent 的分工模式一致。
3. **Python 生态**：均基于 Python 构建，可使用相同的 AI/LLM 依赖栈（LangChain、Pydantic、OpenAI 兼容客户端）。
4. **任务拆分与调度**：Mentis 的 orchestration 理念与本项目的 plan → scheduler → worker → synthesize 流水线高度对应。

### 与本项目的差异点

1. **前端缺失**：Mentis 未提供配套前端工作台，而本项目有完整的 Vue 3 工作台。
2. **LLM 规划层**：Mentis 未见明确的"用 LLM 生成动态 DAG"的模式；本项目的 DeepSeek 主脑负责理解目标并输出结构化 TaskDag，是核心差异化特性。
3. **Agent SDK 绑定**：Mentis 可能使用传统 LangChain Agent，而非本项目使用的 Claude Agent SDK 自主工作循环。
4. **SSE 事件流**：Mentis 未见统一的 SSE 事件推送与前端时间线展示。

### 成熟度评估

- Star 299，体量较小但增长中
- 最近 5 天内有更新，维护活跃
- 定位为框架而非完整工作台

---

## 候选项目 2：AgentHub

| 属性 | 内容 |
|------|------|
| **名称** | AgentHub |
| **仓库地址** | [https://github.com/realyinchen/AgentHub](https://github.com/realyinchen/AgentHub) |
| **简要描述** | 模块化 AI Agent 框架：FastAPI 后端 + TypeScript 前端，集成 LangChain/LangGraph Agent，支持对话智能、推理和工具编排 |
| **主语言** | TypeScript（前后端混合） |
| **Star 数** | ★98 |
| **最近更新** | 2026-07-01 |
| **许可证** | 未指定 |

### 与本项目的相似点

1. **前后端分离架构**：AgentHub 使用 FastAPI（后端）+ TypeScript（前端），与本项目的 Flask + Vue 3 结构高度一致。
2. **LangChain/LangGraph Agent 集成**：两者都将 LangChain/LangGraph 作为 Agent 的执行和编排基础。
3. **工具编排**：均支持 Agent 调用多个工具并协调执行。
4. **Web 工作台**：AgentHub 提供了可视化交互界面，与本项目的 Vue 工作台目标一致。

### 与本项目的差异点

1. **后端框架**：AgentHub 使用 FastAPI（异步），本项目使用 Flask（同步 + 线程）。FastAPI 在 SSE 和并发方面有一定优势，但 Flask 更轻量且本项目明确要求回环地址限制。
2. **无 DAG 规划器**：AgentHub 的 Agent 偏向对话式交互（conversational intelligence），本项目有完整 plan → schedule → worker → synthesize 的 DAG 生命周期。
3. **无 Claude Agent SDK**：AgentHub 使用传统 LangChain Agent 工具链，本项目通过 Claude Agent SDK 实现自主工作循环。
4. **无统一事件系统**：AgentHub 未见本项目的 RunEvent + SQLite + SSE 统一事件流设计。

### 成熟度评估

- Star 98，较小型项目
- 21 天前更新，活跃度一般
- 架构相似度高，适合作为前端交互设计的参考

---

## 候选项目 3：fastapi-mcp-langgraph-template

| 属性 | 内容 |
|------|------|
| **名称** | fastapi-mcp-langgraph-template |
| **仓库地址** | [https://github.com/NicholasGoh/fastapi-mcp-langgraph-template](https://github.com/NicholasGoh/fastapi-mcp-langgraph-template) |
| **简要描述** | 面向 Agent 编排的现代模板，使用 MCP、LangGraph 等社区工具，支持快速迭代和可扩展部署 |
| **主语言** | Python |
| **Star 数** | ★553 |
| **最近更新** | 2026-07-13 |
| **许可证** | 未指定 |

### 与本项目的相似点

1. **LangGraph 编排核心**：以 LangGraph 作为 agentic orchestration 的引擎，与本项目的 build_graph() 设计一致。
2. **MCP 工具集成**：本项目通过 Claude Agent SDK 间接支持 MCP 工具，该模板直接集成了 MCP。
3. **Python 后端 + REST API**：FastAPI 提供 REST 接口，与本项目的 Flask REST 层作用相同。
4. **模板化部署思维**：两者都关注从原型到可扩展部署的路径。

### 与本项目的差异点

1. **模板 vs 完整产品**：该仓库是 template/样板，需在此基础上构建业务逻辑；本项目是功能完整的工作台。
2. **无多 Agent DAG 规划**：模板未实现 LLM 动态生成 DAG 并拆分给多个专业 Agent 的模式。
3. **无前端工作台**：模板为纯后端，本项目有 Vue 3 前端和 SSE 时间线。
4. **无 DeepSeek 主脑模式**：模板不包含"一个规划 LLM + 多个执行 Agent"的分层设计。

### 成熟度评估

- Star 553，在类似项目中较高
- 9 天前更新，活跃维护
- 适合作为 LangGraph + FastAPI 集成方式的参考，也可评估是否用 FastAPI 替代 Flask 的部分能力

---

## 候选项目 4：CrewAI

| 属性 | 内容 |
|------|------|
| **名称** | CrewAI |
| **仓库地址** | [https://github.com/crewAIInc/crewAI](https://github.com/crewAIInc/crewAI) |
| **简要描述** | 角色扮演式自主 AI Agent 编排框架，通过协作智能让 Agent 无缝合作处理复杂任务 |
| **主语言** | Python |
| **Star 数** | ★55,962 |
| **最近更新** | 2026-07-22（本日） |
| **许可证** | 未指定 |

### 与本项目的相似点

1. **多 Agent 协作**：CrewAI 的核心是 role-playing autonomous agents 协作，与本项目的多 Agent 分工（frontend/backend/netty）理念一致。
2. **任务分解**：CrewAI 支持将复杂任务分解为子任务并由不同 Agent 执行，类似本项目的 TaskDag。
3. **Python 生态**：完全基于 Python，与 LangChain/LangGraph 生态兼容。

### 与本项目的差异点

1. **编排范式不同**：CrewAI 使用"角色扮演"（role-playing）和"协作"模式，Agent 之间自主协商；本项目使用 LangGraph 的确定性图编排 + DeepSeek 显式 DAG。
2. **执行模型差异**：CrewAI 的 Agent 更多是"对话协作"，本项目是 plan → schedule → worker → synthesise 的严格阶段化执行。
3. **前端缺失**：CrewAI 为纯 Python 框架/库，不包含 Web 工作台；本项目完整提供 Vue 3 工作台。
4. **持久化与事件**：CrewAI 不内置 SQLite + SSE 统一事件流；本项目的事件系统是核心基础设施。
5. **规模与成熟度**：CrewAI 是行业级的成熟框架（55k+ Stars），本项目是面向特定场景的工作台。

### 成熟度评估

- Star 55,962，行业顶级项目
- 本日仍在更新，生态极其活跃
- 适合作为"多 Agent 分工模式"的理念参考，但在编排机制上走的是不同路线

---

## 候选项目 5：LangGraph（langchain-ai/langgraph）

| 属性 | 内容 |
|------|------|
| **名称** | LangGraph |
| **仓库地址** | [https://github.com/langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) |
| **简要描述** | 构建弹性 Agent 的框架（Build resilient agents） |
| **主语言** | Python |
| **Star 数** | ★37,855 |
| **最近更新** | 2026-07-22（本日） |
| **许可证** | MIT |

### 与本项目的相似点

1. **基础设施依赖**：本项目直接依赖 LangGraph 作为编排引擎（StateGraph、Send、barrier、reducer）。
2. **相同的图编排模型**：本项目的 plan → scheduler → worker → barrier → synthesize 图结构直接基于 LangGraph 的 StateGraph API。
3. **动态并行任务**：两者都使用 `Send` API 实现动态数量的并行 worker 分发。
4. **Python 生态深度绑定**：Pydantic、TypedDict、operator.add reducer 等模式完全一致。

### 与本项目的差异点

1. **层级不同**：LangGraph 是底层框架，本项目是应用层工作台。LangGraph 不包含 Flask API、DeepSeek 规划器、Vue 前端、SQLite 持久化。
2. **角色不同**：LangGraph 面向所有 Agent 构建者；本项目面向"软件工程 Agent 工作台"这一特定领域。
3. **无 Agent 定义管理**：LangGraph 不管理 Agent Markdown 定义、Skill 配置、工作目录持久化；这些都是本项目的上层能力。

### 成熟度评估

- Star 37,855，LangChain 生态核心项目
- 每日活跃更新，MIT 许可证
- 本项目最重要的上游依赖，持续关注其新特性（如 checkpointer、interrupt、streaming）对项目有直接价值

---

## 对比总结

| 维度 | 本项目 (Agent Studio) | Mentis | AgentHub | fastapi-mcp-lg-template | CrewAI | LangGraph |
|------|----------------------|--------|----------|------------------------|--------|-----------|
| **图编排引擎** | LangGraph | LangGraph | LangChain/LangGraph | LangGraph | 自研 | LangGraph |
| **LLM 规划 DAG** | ✅ DeepSeek 主脑 | ❌ | ❌ | ❌ | 隐式 | ❌ |
| **Agent SDK** | Claude Agent SDK | LangChain Agent | LangChain Agent | LangChain + MCP | 自研 Agent | 不限定 |
| **并行执行** | ✅ Send + barrier | ✅ | 部分 | ✅ | ✅ | ✅ |
| **前端工作台** | ✅ Vue 3 | ❌ | ✅ TS 前端 | ❌ | ❌ | ❌ |
| **统一事件流** | ✅ SSE + SQLite | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Skill 配置** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **回环安全限制** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Star 数** | — | 299 | 98 | 553 | 55,962 | 37,855 |

---

## 建议

1. **Mentis** 是最接近本项目架构的同类项目，建议持续关注其 LangGraph 编排模式和 Agent 注册机制。
2. **fastapi-mcp-langgraph-template** 的 FastAPI + LangGraph 集成模式可作为未来若需升级到异步框架时的参考。
3. **AgentHub** 的前后端分离架构和 UI 交互设计值得参考，特别是在 Agent 状态可视化和对话式编排方面。
4. **CrewAI** 虽然在编排理念上与本项目不同，但其"角色定义 → 任务分配 → 协作执行"的模式可为 Agent 角色设计提供灵感。
5. **LangGraph** 作为上游依赖，其 checkpointer、interrupt（Human-in-the-Loop）、streaming 等新特性可直接提升本项目的断点恢复和实时流能力。
