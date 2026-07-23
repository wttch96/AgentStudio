# Agent Studio

Agent Studio 是一个仅在本机运行的多项目软件工程 Agent 工作台。你先选择一个包含待改造项目的工作空间，再描述目标；Claude 专业 Agent 会搜索并过滤真实项目，DeepSeek 主脑根据发现结果选择项目、定义跨项目契约并生成实施 DAG，LangGraph 负责分流、并行执行和汇流。

项目内置三个可配置的执行 Agent：

- `frontend-agent`：发现并处理工作空间中的 Web 前端项目，不限定固定目录或框架。
- `backend-agent`：发现并处理工作空间中的业务后端、API 和持久化项目。
- `netty-agent`：Netty 数据接收、协议解析、编码发送和传输测试。

> 项目强制绑定 `127.0.0.1`，配置、任务记录、Token 统计和工作目录信息都保存在本机。

## 主要功能

### 项目发现、契约规划和并行执行

- 相关专业 Agent 先在所选工作空间中递归搜索构建清单、源码入口和已有接口，过滤候选项目；不会假定项目叫 `frontend/`、`backend/` 或 `netty/`。
- 发现结果汇流后，DeepSeek 选择实际项目并生成共享 HTTP API 或二进制协议契约。
- DeepSeek 再生成经过校验的实施 DAG，任务携带真实项目相对路径和精确 `write_scope`。
- LangGraph 按依赖关系把可并行节点同时分发给 Claude Agent；契约明确后，前后端可以同步编码而不必互相等待。
- 每一批 Agent 完成后经过显式 barrier 汇流，再执行下游节点。
- DeepSeek 在普通任务结束时读取全部执行结果并做最终验收。

### 任务流程图（DAG 可视化）

- 顶部始终显示任务流程图为 SVG 图结构：主脑规划 → 各任务节点 → 结果汇总。
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

### 指定 Agent 和失败重试

聊天框支持斜杠命令：

| 命令 | 作用 |
| --- | --- |
| `/frontend <指令>` | 直接交给 `frontend-agent` |
| `/backend <指令>` | 直接交给 `backend-agent` |
| `/netty <指令>` | 直接交给 `netty-agent` |
| `/agent <frontend\|backend\|netty> <指令>` | 使用统一格式选择 Agent |
| `/retry <task-id>` | 重试当前上游运行中的失败节点 |

直接选择 Agent 时会跳过 DeepSeek 规划和最终汇总，由 LangGraph 运行单个 Claude Agent，并把 Agent 结果直接作为本轮输出。失败的 DAG 节点也会在页面上显示"重试"按钮。

### 页面配置中心

无需手工编辑项目文件，即可在页面内管理：

- DeepSeek 主脑的规划决策提示词和最终验收提示词。
- **记忆系统配置**：滑动窗口大小、压缩阈值、衰减率、归档时间等 8 项参数。
- Agent 的用途、系统提示词、工具权限和关联 Skill。
- Skill 的创建、内容修改和 Agent 分配。
- 默认工作目录的浏览、选择和持久化。
- LangGraph 最大并行数、图递归上限、Agent 轮次和超时。

默认主脑模板位于 `config/brain.default.json`。页面保存后的本机覆盖配置写入 `bac