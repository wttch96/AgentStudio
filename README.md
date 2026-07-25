# Agent Studio

本机多 Agent 协作工作台。DeepSeek 主脑编排 + 确定性流程引擎，LangGraph 调度执行，LangMem 分层记忆。

> 强制绑定 `127.0.0.1`，配置用 YAML 文件手动编辑，运行数据存 SQLite。

## 项目结构

```
├── templates/                 ← 全局模板（可 git 版本控制）
│   ├── agents/                ← Agent 模板 (10个内置)
│   ├── flows/                 ← 流程定义 (3个示例)
│   ├── project/               ← 新建项目的 .agent-studio/ 骨架
│   └── brain.default.json     ← 主脑默认提示词
│
├── .workspace/                ← 当前运行时配置
│   └── .agent-studio/
│       ├── project.yaml       ← 项目定义
│       ├── brain.yaml         ← 主脑提示词
│       ├── scheduler.yaml     ← 调度参数
│       ├── memory.yaml        ← 记忆策略
│       ├── agents/            ← 当前启用 Agent
│       ├── skills/            ← 项目 Skill
│       ├── flows/             ← 项目流程
│       └── db/                ← SQLite (不入 git)
├── backend/                   ← Flask + LangGraph + Claude SDK
├── frontend/                  ← Vue 3 + TypeScript + Vite
└── start.sh / stop.sh
```

## 架构

```
用户目标 → 流程匹配 (FlowEngine) 或 主脑编排 (DeepSeek) → DAG
         → LangGraph 调度分发
              ├─ Claude Agent SDK (编码、文件操作)
              ├─ 文件操作 Agent (FileManagementToolkit)
              └─ RAG Agent (知识检索录入)
         → 结果汇流 → 下一轮
              ↓
         LangMem 记忆压缩 + 长期提取
```

## Agent 团队

| Agent | 引擎 | 用途 |
|-------|------|------|
| **Claude Agent** | Claude Agent SDK | 编码、审查、文件操作 |
| **文件操作 Agent** | LangChain + FileManagementToolkit | 文件复制/移动/删除/搜索 |
| **RAG Agent** | LangChain | 知识检索和录入 |
| **代码审查** | Claude Agent SDK | 只读代码质量审查 |
| **文档对比** | Claude Agent SDK | 文档/接口差异检测 |
| **接口设计** | Claude Agent SDK | RESTful API 设计 |
| **主脑** | DeepSeek API | 意图分类和 DAG 编排 |

## 快速开始

```bash
cp .env.example .env    # 填入 API Key
./start.sh              # 启动后端(5000)+前端(5173)
```

## 手动创建项目

```bash
cp -r templates/project/.agent-studio your-project/.workspace/.agent-studio
# 编辑 project.yaml、agents/*.yaml 等
# 启动后在 UI 中选择工作目录
```

## 命令

| 命令 | 说明 |
|------|------|
| 直接输入 | 主脑分析并生成 DAG |
| `/+流程名` | 执行预定义流程 |
| `/agent <名> <指令>` | 指定 Agent |
| `/frontend` / `/backend` | 快捷引导 |
| `/retry <task-id>` | 重试失败节点 |

## 数据存储

| 存储 | 位置 | 形式 |
|------|------|------|
| **用户配置** | `.workspace/.agent-studio/` 和 `templates/` | YAML 文件 |
| **运行历史** | `.workspace/.agent-studio/db/agents-manager.db` | SQLite |
| **知识库** | 同上 | SQLite + FTS5 |
| **状态快照** | `.agent-studio-checkpoints.db` | SQLite (SqliteSaver) |
