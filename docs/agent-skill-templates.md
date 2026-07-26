# Agent 与 Skill 模版

Agent Studio 把可复用定义和项目运行实例分开保存：

```text
templates/agents/*.yaml          全局 Agent 模版，显示在模版中心
templates/skills/*.yaml          全局 Skill 模版，显示在模版中心
templates/project/agents/*.yaml  新项目的 Agent 种子实例
templates/project/skills/*.yaml  新项目的 Skill 种子实例
.workspace/<project_id>/...      当前项目实际使用的可编辑副本
```

新建项目时，`templates/project/` 会被复制到
`.workspace/<project_id>/`。之后修改项目副本不会反向修改全局模版，修改全局模版也不会
覆盖已经创建的项目。

## 内置 Agent 模版

以下 YAML 会被后端直接加载到 Agent 模版中心。后端还保留同名的内联默认定义，用于首次
启动时补齐缺失文件；定义位置见
[`BUILTIN_TEMPLATES`](../backend/app/services/project_manager.py)。YAML 文件是可查看和
维护的模版来源。

| 模版 | 类型 | 默认目录 | 用途 | 源文件 |
| --- | --- | --- | --- | --- |
| DeepSeek 主脑 | 项目配置 | 项目根目录 | 目标理解、规划、DAG 和验收 | [brain.yaml](../templates/project/brain.yaml) |
| RAG | `rag` | 项目根目录 | 知识检索、录入和来源整理 | [rag.yaml](../templates/agents/rag.yaml) |
| Vue 前端 | `claude` | `frontend` | Vue 3、TypeScript 和前端验证 | [vue-frontend.yaml](../templates/agents/vue-frontend.yaml) |
| React 前端 | `claude` | `frontend` | React、TypeScript 和前端验证 | [react-frontend.yaml](../templates/agents/react-frontend.yaml) |
| Flask 后端 | `claude` | `backend` | Flask API、数据和后端测试 | [flask-backend.yaml](../templates/agents/flask-backend.yaml) |
| SpringBoot 后端 | `claude` | `backend` | SpringBoot API、JPA 和测试 | [springboot-backend.yaml](../templates/agents/springboot-backend.yaml) |
| Netty 数据服务 | `claude` | `netty` | TCP/UDP、协议编解码和传输测试 | [springboot-netty.yaml](../templates/agents/springboot-netty.yaml) |
| 代码审查 | `claude` | 项目根目录 | 只读代码质量、安全和测试审查 | [code-reviewer.yaml](../templates/agents/code-reviewer.yaml) |
| 文档对比 | `claude` | 项目根目录 | 文档、接口和实现一致性检查 | [doc-diff.yaml](../templates/agents/doc-diff.yaml) |
| 接口设计 | `claude` | 项目根目录 | REST API、数据模型和公共契约 | [api-designer.yaml](../templates/agents/api-designer.yaml) |

仓库还提供包含能力边界、输入输出契约、优先级和迭代上限的增强参考模版：

- [主脑编排 Agent](../templates/agents/master-brain.yaml)
- [前端代码 Agent](../templates/agents/frontend-enhanced.yaml)
- [后端代码 Agent](../templates/agents/backend-enhanced.yaml)
- [RAG 知识检索 Agent](../templates/agents/rag-enhanced.yaml)
- [文件操作 Agent](../templates/agents/file-ops-enhanced.yaml)
- [文档处理 Agent](../templates/agents/document-enhanced.yaml)

## Agent YAML 字段

一个可直接使用的 Agent 模版示例：

```yaml
name: vue-frontend
display_name: Vue 前端
description: Vue 3、TypeScript、组件、交互和前端验证
role: implementation_agent
agent_type: claude
sub_dir: frontend
system_prompt: 你是 Vue 3 前端专家……
skills:
  - collaboration-protocol
  - board-operations
  - structured-result
  - rtk-output-compression
  - concise-agent-output
capabilities: [Vue 3, TypeScript, frontend_development]
limitations: [不负责数据库设计]
preferred_tasks: [前端, 页面, 组件]
forbidden_tasks: [数据库迁移]
input_contract: {api_contract: 接口契约}
output_contract: {verification: 构建测试结果}
priority: 6
max_iterations: 6
```

完整实例见[项目 Vue Agent](../templates/project/agents/vue-frontend.yaml)。其中：

- `agent_type` 决定执行器，常用值为 `brain`、`claude`、`rag` 和 `file-ops`。
- `sub_dir` 是相对项目代码根目录的默认工作目录，空字符串表示项目根目录。
- `skills` 按名称引用当前项目 `skills/` 目录中的 Skill，专项规范直接以这里的选择为准。
- Claude SDK 的工具权限不在 Agent 模板中预批准，由项目 Mode、任务写入范围和执行器统一控制。
- `capabilities`、`preferred_tasks` 和 `priority` 参与主脑选人及调度。
- `limitations` 与 `forbidden_tasks` 描述不可逾越的任务边界。
- `input_contract`、`output_contract` 和 `max_iterations` 用于约束交接与返工。

## 内置 Skill 模版

模版中心当前提供两个可复用 Skill：

| Skill | 用途 | 源文件 |
| --- | --- | --- |
| `rtk-output-compression` | 优先使用等价 RTK 命令压缩搜索、构建、测试和日志输出 | [rtk-output-compression.yaml](../templates/skills/rtk-output-compression.yaml) |
| `concise-agent-output` | 删除寒暄、任务复述、过程旁白和重复总结，保留可核验结果 | [concise-agent-output.yaml](../templates/skills/concise-agent-output.yaml) |

新项目还会内置以下协作 Skill。它们作为项目种子直接复制，不显示为全局发布模版：

| Skill | 用途 | 项目种子文件 |
| --- | --- | --- |
| `collaboration-protocol` | 多 Agent 统一交接字段和协作边界 | [collaboration-protocol.yaml](../templates/project/skills/collaboration-protocol.yaml) |
| `board-operations` | Todo、阻塞、决策和产物的看板写入规则 | [board-operations.yaml](../templates/project/skills/board-operations.yaml) |
| `structured-result` | 统一 Agent 最终结果状态和结构 | [structured-result.yaml](../templates/project/skills/structured-result.yaml) |
| `review-and-verification` | Reviewer 验收和返工协议 | [review-and-verification.yaml](../templates/project/skills/review-and-verification.yaml) |
| `safe-file-operations` | 工作区、覆盖、删除和递归操作边界 | [safe-file-operations.yaml](../templates/project/skills/safe-file-operations.yaml) |
| `flow-authoring` | 条件、并行、汇流、循环和节点配置规则 | [flow-authoring.yaml](../templates/project/skills/flow-authoring.yaml) |
| `rtk-output-compression` | RTK 输出压缩规则的项目副本 | [rtk-output-compression.yaml](../templates/project/skills/rtk-output-compression.yaml) |
| `concise-agent-output` | 精简输出规则的项目副本 | [concise-agent-output.yaml](../templates/project/skills/concise-agent-output.yaml) |

## Skill YAML 与挂载方式

Skill 文件由名称、说明和指令正文组成：

```yaml
name: concise-agent-output
description: 直接输出结论、变更和验证
content: |
  首句给结论或阻塞，不寒暄、不复述任务……
```

Agent 通过 `skills` 数组挂载 Skill：

```yaml
skills:
  - collaboration-protocol
  - structured-result
  - concise-agent-output
```

运行时会按名称从当前项目 `.workspace/<project_id>/skills/` 加载正文并注入 Agent
上下文。引用名称必须与 Skill 文件中的 `name` 一致；删除或改名 Skill 前，应先更新所有
Agent 的 `skills` 引用。

## 新项目默认 Agent 与 Skill 组合

项目种子已经给不同职责配置了适合的 Skill：

| Agent | 项目种子文件 | 默认 Skill 重点 |
| --- | --- | --- |
| 接口设计 | [api-designer.yaml](../templates/project/agents/api-designer.yaml) | 协作、看板、结构化结果、RTK、精简输出 |
| Flask 后端 | [flask-backend.yaml](../templates/project/agents/flask-backend.yaml) | 协作、看板、结构化结果、RTK、精简输出 |
| Vue 前端 | [vue-frontend.yaml](../templates/project/agents/vue-frontend.yaml) | 协作、看板、结构化结果、RTK、精简输出 |
| 代码审查 | [code-reviewer.yaml](../templates/project/agents/code-reviewer.yaml) | 看板、验收、RTK、精简输出 |
| 文档对比 | [doc-diff.yaml](../templates/project/agents/doc-diff.yaml) | 结构化结果、验收、RTK、精简输出 |
| 文件操作 | [file-ops-agent.yaml](../templates/project/agents/file-ops-agent.yaml) | 看板、安全文件操作、精简输出 |
| RAG | [rag.yaml](../templates/project/agents/rag.yaml) | 协作、结构化结果、精简输出 |

修改模版后，可以在“项目管理”中新建项目验证种子结果；已有项目应在“配置中心”直接更新
自己的 Agent 和 Skill 副本。
