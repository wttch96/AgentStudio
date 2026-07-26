# Agent Studio 技术架构

> 使用方式见 [README](../README.md)。

## 系统架构

```text
Vue 3 / TypeScript
        │ REST + SSE
Flask API / ServiceContainer
        ├─ ProjectManager + ConfigReader
        ├─ DeepSeekPlanner + PlanValidator
        ├─ LangGraph Scheduler + ConflictDetector
        ├─ AgentContextBuilder + Blackboard + Todo
        ├─ Claude / RAG / Chat / File / Document Executors
        ├─ WaveReviewer
        ├─ KnowledgeStore + MemoryManager
        └─ SQLiteStore + AsyncSqliteSaver
```

## 执行协议

```text
START
  → load current project
  → discovery
  → build and validate plan
  → schedule ready tasks
  → worker × N
  → barrier
  → review
      ├─ revision_required → replan → scheduler
      └─ accepted → compact memory
  → final synthesis
  → extract memory
  → END
```

- 简单请求可跳过执行图，由主脑直接回答。
- 直接指定 Agent 时跳过 discovery 和主脑汇总。
- discovery 严格只读，实施任务必须满足上游依赖。
- Scheduler 只分发当前依赖已满足的任务，并检测重叠写入范围。
- Reviewer 不重写产物，只给出验收决策和返工要求。
- 图循环、重新规划和 Agent 迭代均有硬上限。

## Agent 配置

内置 Agent、增强参考 Agent、项目种子 Skill 及其真实 YAML 文件索引见
[Agent 与 Skill 模版](agent-skill-templates.md)。

每个项目 Agent YAML 支持：

```yaml
name: backend-agent
display_name: 后端 Agent
role: implementation_agent
description: 负责 API、数据和后端测试
agent_type: claude
sub_dir: backend
capabilities: [backend, api, database]
limitations: [不负责前端视觉设计]
preferred_tasks: [接口, 后端]
forbidden_tasks: [修改前端代码]
skills: []
input_contract: {}
output_contract: {}
dependencies_info: [python >= 3.11]
priority: 5
max_iterations: 6
system_prompt: |
  ...
```

主脑选择 Agent 时综合能力、限制、禁止项、已关联 Skill、任务偏好、优先级和当前负载，
不只匹配名称。

## 上下文与看板

进入 worker 前，`AgentContextBuilder` 自动注入：

- 当前任务、预期产物和验收条件；
- 写入范围、工具范围、禁止操作和迭代上限；
- 上游结果与下游消费者；
- 协调契约、已有决策、产物和阻塞；
- 当前 Blackboard 和 Todo 状态。

执行结果写回 Blackboard；Todo 保存任务状态。Prompt 提供行为软约束，Pydantic Schema
约束结构，LangGraph 约束流程，项目 Mode、任务写入范围和执行器约束真实操作，
Reviewer 约束质量。

## 执行可视化

工作台从同一组运行、任务和事件数据派生五种视图：

| 视图 | 表达重点 | 布局规则 |
| --- | --- | --- |
| DAG 图 | 对话轮次、主脑、依赖和执行节点 | 从左到右自动分层；历史对话轮次使用固定顺序，不因节点更新时间改变位置 |
| 时间轴 | 主脑思考、调度批次和 Agent 内部事件 | 主轴及 Agent 内部轴垂直向下；串行不分叉；仅并发使用圆角正交折线分流和汇流 |
| 时序图 | Agent 调用先后、并发区间和返回关系 | 时间从上到下推进，消息带方向箭头，并发调用纵向分组展示 |
| 看板 | Todo 状态、负责人、验收信息和共享数据 | 按待处理、进行中、审查、完成分列；节点共享键值折叠显示 |
| 事件记录 | 原始 SSE 事件 | 按事件序号和时间排序，供排障与协议核对 |

时间轴连接规则：

1. 主轴使用一条连续、可辨识的垂直线，主脑和调度图标居中落在轴线上。
2. 单 Agent 批次直接沿主轴进入 Agent 卡片，不绘制分流或汇流折线。
3. 并发批次从主轴向下后圆角右转，再向下接入每个 Agent 头部；结束时使用对称折线回到主轴。
4. Agent 头像、工具调用、消息和完成/失败节点共用同一条内部垂直轴。
5. 分流和汇流端点读取实际 DOM 像素坐标；列宽、横向滚动区域或窗口尺寸变化时通过
   `ResizeObserver` 重新计算，避免使用百分比估算造成错位。
6. 主轴图标保持紧凑，并为标题正文预留固定间距，不能覆盖文字。

对应实现见
[ThinkingTimeline.vue](../frontend/src/components/ThinkingTimeline.vue)、
[AgentSequenceDiagram.vue](../frontend/src/components/AgentSequenceDiagram.vue) 和
[TodoPanel.vue](../frontend/src/components/TodoPanel.vue)。

## Agent 类型

| `agent_type` | 执行器 | 主要职责 |
| --- | --- | --- |
| `brain` | DeepSeekPlanner | 理解、规划、委派、验收、汇总 |
| `claude` | ClaudeAgentExecutor | 代码、测试和工具执行 |
| `rag` | RAGAgentExecutor | 可追溯知识检索与录入 |
| `file-ops` | FileAgentExecutor | 受工作区约束的文件操作 |
| `chat` | ChatExecutor | 文档和通用内容处理 |
| `doc-diff` | DocDiffAgentExecutor | 只读差异审查 |
| `blackboard` | BlackboardAgentExecutor | 共享契约、决策和产物 |
| `todo` | TodoStore | 任务看板状态 |

## 项目隔离

`.workspace/current-project.yaml` 是当前项目的唯一入口：

```yaml
project_id: agent-studio
```

运行时目录：

```text
.workspace/<project_id>/
├── project.yaml
├── brain.yaml
├── workspace.yaml
├── scheduler.yaml
├── memory.yaml
├── agents/
├── skills/
├── flows/
└── db/
    ├── agents-manager.db
    └── checkpoints.db
```

切换当前项目时会重建服务容器，使业务数据库、checkpoint、知识、记忆、运行、事件和看板同时切换。项目 YAML 是配置主源；SQLite 保存运行期数据。

## SQLite 数据

| 数据 | 位置 |
| --- | --- |
| 项目配置 | 项目目录下的 YAML |
| Agent / Skill / Flow | 项目目录下对应子目录 |
| 运行与事件 | `db/agents-manager.db` |
| RAG、关系与反馈 | `db/agents-manager.db` |
| Blackboard 与 Todo | `db/agents-manager.db` |
| 分层记忆 | `db/agents-manager.db` |
| LangGraph checkpoint | `db/checkpoints.db` |

SQLite 使用 WAL 和 FTS5。知识检索优先 BM25；向量扩展或 embedding 不可用时安全降级。

## 日志与排障

`start.sh` 从后端进程启动起把日志同步输出到终端，并写入 `.run/backend.log`。日志包含
线程、模块、Request ID、项目与运行 ID、HTTP 耗时、规划、Flow/DAG、Agent 生命周期、
重试及异常堆栈；不记录请求正文和密钥。默认 `INFO`，`LOG_LEVEL=DEBUG` 会记录每条内部
事件。启动时轮换并保留最近五份历史日志，详细开关见[自举与本地启动](bootstrap.md)。

## 本机安全边界

- Flask 和 Vite 只允许绑定回环地址。
- API 不返回模型密钥。
- 项目标识经过安全字符校验，不能形成路径穿越。
- Claude cwd 固定为项目工作目录，任务还会携带 `write_scope`。
- 文件 Agent 禁止无授权递归删除，覆盖和批量移动属于高风险操作。

## 验证

```bash
cd backend && .venv/bin/pytest -q
cd frontend && npm run build
```
