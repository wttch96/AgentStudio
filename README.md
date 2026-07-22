# Agent Studio

Agent Studio 是一个仅在本机运行的软件工程 Agent 工作台。你只需要描述目标，DeepSeek 会生成任务 DAG，LangGraph 负责并行调度和汇流，Claude 专业 Agent 则读取项目、调用工具、加载 Skill 并完成实际工作。

项目内置三个可配置的执行 Agent：

- `frontend-agent`：Vue、TypeScript、页面交互和前端构建。
- `backend-agent`：Flask、Python、LangGraph 编排和后端测试。
- `netty-agent`：Netty 数据接收、协议解析、编码发送和传输测试。

> 项目强制绑定 `127.0.0.1`，配置、任务记录、Token 统计和工作目录信息都保存在本机。

## 主要功能

### 自动规划和并行执行

- DeepSeek 根据目标和工作区结构生成经过校验的任务 DAG。
- LangGraph 按依赖关系把可并行节点同时分发给 Claude Agent。
- 每一批 Agent 完成后经过显式 barrier 汇流，再执行下游节点。
- DeepSeek 在普通任务结束时读取全部执行结果并做最终验收。

### 可观察的 Agent 时间线

- 实时显示规划、分流、Agent 启动、工具调用、Skill 加载、汇流和最终输出。
- 多个 Agent 在独立泳道中并行展示。
- 每条 Agent 泳道可以独立折叠，折叠后保留任务标题和运行状态。
- 连续的同名工具调用自动合并，展开后仍能查看每次调用参数。
- 正在工作的 Agent 会在右侧状态栏持续闪烁，完成或失败后自动停止。
- 失败节点显示完整错误类型、摘要和执行器返回原因。

### 连续任务

选中一个已结束的历史任务后继续输入，聊天框会进入“继续”模式。新一轮会继承：

- 上游目标与最终输出。
- Claude Agent 的执行结果和失败摘要。
- 原任务使用的工作目录。
- 最近最多 8 轮、总计不超过 24,000 字符的本地上下文。

点击左侧“新建任务”后才会创建不携带历史上下文的新对话链。

### 指定 Agent 和失败重试

聊天框支持斜杠命令：

| 命令 | 作用 |
| --- | --- |
| `/frontend <指令>` | 直接交给 `frontend-agent` |
| `/backend <指令>` | 直接交给 `backend-agent` |
| `/netty <指令>` | 直接交给 `netty-agent` |
| `/agent <frontend\|backend\|netty> <指令>` | 使用统一格式选择 Agent |
| `/retry <task-id>` | 重试当前上游运行中的失败节点 |

直接选择 Agent 时会跳过 DeepSeek 规划和最终汇总，由 LangGraph 运行单个 Claude Agent，并把 Agent 结果直接作为本轮输出。失败的 DAG 节点也会在页面上显示“重试”按钮。

### 页面配置中心

无需手工编辑项目文件，即可在页面内管理：

- Agent 的用途、系统提示词、工具权限和关联 Skill。
- Skill 的创建、内容修改和 Agent 分配。
- 默认工作目录的浏览、选择和持久化。
- LangGraph 最大并行数和图递归上限。
- Claude Agent 最大交互轮次和单节点超时时间。

Agent 与 Skill 的配置分别写入 `agents/*.md` 和 `.claude/skills/*/SKILL.md`。

### DeepSeek 余额和本地用量

- 查询 DeepSeek 账户可用余额、充值余额和赠送余额。
- 本地记录本项目发起的 DeepSeek 输入、缓存命中、缓存未命中和输出 Token。
- 汇总今日、本月和本地累计用量。
- 根据 `.env` 中的单价估算美元花费，并明确标注“本地统计 · 费用估算”。

本地用量不会补录启用前或其他客户端产生的请求，估算金额也不等同于 DeepSeek 官方账单。

### 本地任务管理

- SQLite 持久化任务、事件、对话链和 DeepSeek 用量。
- 支持停止活动任务和删除终态任务记录。
- 自动清理后端重启后遗留的脏运行状态。
- 左右侧栏默认打开，可分别折叠，让中间工作区自动扩展。
- SSE 断线后按照事件序号恢复，减少重复时间线记录。

## 快速开始

需要 Python 3.11+、Node.js 20+ 和 npm。

项目默认提供 CC Switch 本地路由示例：

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

1. 打开右上角“配置中心”，选择需要操作的本地项目目录。
2. 根据任务复杂度调整 Agent 最大轮次、超时时间和并行数量。
3. 在聊天框描述目标，或输入 `/` 直接选择专业 Agent。
4. 在时间线中观察 DeepSeek 规划、LangGraph 分流和 Claude 工具调用。
5. 任务结束后直接继续输入，基于上游输出开始下一轮。
6. 某个节点失败时点击“重试”，或输入 `/retry <task-id>`。

## 项目结构

```text
AgentsManager/
├── frontend/          Vue 3 + TypeScript 管理界面
├── backend/           Flask API、LangGraph、模型适配和 SQLite
├── agents/            三个内置 Claude Agent 声明
├── .claude/skills/    项目级 Skill
├── config/            Claude / CC Switch 配置示例
├── docs/              技术架构和截图素材
├── start.sh           本地一键启动
└── stop.sh            停止本地服务
```

## 文档

- [完整技术架构、LangGraph 流程和 Agent/Skill 说明](docs/technical-architecture.md)

## 界面截图

### 并行 Agent 与执行时间线

![Agent Studio 工作台总览](docs/images/workspace-overview.png)

### 页面配置中心

![页面配置中心](docs/images/configuration-center.png)

### 斜杠命令菜单

![斜杠命令菜单](docs/images/slash-commands.png)

### 连续任务上下文

![连续任务上下文](docs/images/task-continuation.png)
