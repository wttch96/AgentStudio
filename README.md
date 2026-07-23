# Agent Studio

本机多 Agent 协作工作台。DeepSeek 主脑编排多 Agent 团队，LangGraph 调度执行，LangMem 管理分层记忆。

> 强制绑定 `127.0.0.1`，所有数据保存在本机 SQLite。

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

## 快速开始

Python 3.11+ / Node.js 20+.

```bash
cp .env.example .env   # 填入 API Key
./start.sh             # 一键启动
```

访问 `http://127.0.0.1:5173`。停止：`./stop.sh`

```dotenv
DEEPSEEK_API_KEY=sk-...        # 必填（主脑 + RAG + DeepSeek Agent）
ANTHROPIC_BASE_URL=http://127.0.0.1:15721  # CC Switch
ANTHROPIC_AUTH_TOKEN=PROXY_MANAGED
```

## 使用流程

1. **创建项目** → 选择工作目录，勾选 Agent 模板
2. **描述目标** → 主脑编排 DAG，Agent 并行执行
3. **持续引导** → 执行中输入新指令即注入为引导上下文
4. **对话历史** → 所有对话和主脑响应在 DAG 上方展示
5. **停止/中断** → DAG 旁停止按钮、聊天框中断按钮
6. **模板可编辑** → 配置中心修改模板，新建 Agent 自动应用

## 命令

| 命令 | 说明 |
|------|------|
| 直接输入 | 主脑分析目标并生成 DAG |
| `/agent <名> <指令>` | 定向引导指定 Agent |
| 运行中输入 | 注入为引导上下文（不创建新任务） |

## 配置中心

| Tab | 说明 |
|-----|------|
| 主脑配置 | 统一编排提示词 |
| RAG 配置 | RAG Agent 提示词 |
| Agent 配置 | 新增/编辑/删除，按类型区分字段 |
| Skill 编辑 | 项目级 Skill |
| 工作目录 | 默认工作空间 |
| 调度配置 | 并行数/超时 |
| 记忆配置 | 短期(滑动窗口) + 长期(归档衰减) |

## 记忆系统

| 层 | 技术 | 触发 |
|----|------|------|
| **短期** | SqliteSaver + 滑动窗口压缩 | 每个 wave 后 |
| **长期** | LangMem MemoryStoreManager + ThreadExtractor | 执行完成后 |
| **策略** | StrategyEngine 配置驱动 | token/轮次/闲置阈值 |

## 项目结构

```
├── frontend/src/components/
│   ├── ChatHistory.vue      对话历史
│   ├── DagGraph.vue          DAG 流程图
│   ├── EventTimeline.vue     执行时间线
│   ├── PromptComposer.vue    聊天输入 + 中断
│   ├── AgentInspector.vue    右侧 Agent 状态 + Token 统计
│   └── config/               配置中心 7 标签页
├── backend/app/
│   ├── agents/               Claude/DeepSeek/RAG 三执行器
│   ├── orchestration/graph.py LangGraph 图 (含 memory 节点)
│   ├── planning/             DeepSeek DAG 编排器
│   ├── services/             项目/知识库/记忆/配置
│   └── storage/              SQLite (FTS5 + 触发器)
├── config/                   默认配置
├── start.sh / stop.sh
└── .env.example
```

## Token 优化

- 提示词内置 RTK 指令 (`rtk` 前缀节省 60-90% CLI token)
- 右侧面板实时显示每个 Agent 输入/输出 token
- 工具调用建议只读取需要的文件片段

## API

| 端点 | 说明 |
|------|------|
| `GET/POST/DELETE /api/projects` | 项目 CRUD |
| `GET/POST/PUT/DELETE /api/projects/{id}/agents` | 项目 Agent |
| `GET/POST/PUT/DELETE /api/templates` | 模板管理 |
| `GET/POST/PUT/DELETE /api/knowledge` | 知识库 |
| `GET/POST/PUT /api/skills` | Skill |
| `GET/PUT /api/brain` | 主脑配置 |
| `POST/GET/DELETE /api/runs` | 任务运行 |
| `POST /api/runs/{id}/interrupt` | 中断/注入 |
| `GET/PUT /api/memory` | 记忆配置 |
| `GET/PUT /api/scheduler` | 调度配置 |
| `GET /api/template-center` | 模板中心 |
