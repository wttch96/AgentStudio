# Agent Studio Project Template

## 目录结构

```
my-project/
├── .agent-studio/           ← Agent Studio 配置目录
│   ├── project.yaml         ← 项目定义
│   ├── brain.yaml           ← 主脑编排提示词
│   ├── workspace.yaml       ← 工作空间路径
│   ├── scheduler.yaml       ← 调度参数
│   ├── memory.yaml          ← 记忆策略
│   ├── agents/              ← Agent 定义（每个 Agent 一个 YAML）
│   │   └── my-agent.yaml
│   ├── skills/              ← 项目级 Skill（每个 Skill 一个 YAML）
│   │   └── deploy.yaml
│   ├── flows/               ← 流程定义（每个流程一个 YAML）
│   │   └── my-flow.yaml
│   └── db/                  ← 运行时数据库（自动生成）
│       ├── agents-manager.db
│       └── checkpoints.db
└── src/                     ← 你的项目代码
```

## 使用方式

1. 复制 `config/templates/project/` 到你的项目根目录
2. 编辑 `.agent-studio/project.yaml` 填写项目名
3. 编辑 `.agent-studio/workspace.yaml` 填写项目路径
4. 在 `.agent-studio/agents/` 中添加 Agent 定义
5. 在 `.agent-studio/flows/` 中添加流程定义
6. 启动 Agent Studio

## Agent 定义示例

```yaml
# .agent-studio/agents/code-reviewer.yaml
name: code-reviewer
display_name: 代码审查
description: 专注代码质量审查
agent_type: claude
sub_dir: ""
system_prompt: |
  你是专业代码审查专家...
tools: [Read, Glob, Grep]
skills: []
sort_order: 0
```

## 流程定义示例

```yaml
# .agent-studio/flows/code-review.yaml
name: code-review
description: 代码审查流程
version: "1.0"
keywords: [review, 审查]
nodes:
  - id: review
    agent: code-reviewer
    title: 审查代码
    objective: 审查最新变更...
    depends_on: []
synthesize:
  template: |
    ## 审查结果
    {{ review.output.summary }}
```

## 全局配置参考

| 文件 | 说明 |
|------|------|
| `config/templates/agents/` | 全局 Agent 模板（跨项目复用）|
| `config/templates/project/` | 项目模板（新建项目时复制）|
| `config/flows/` | 全局流程定义 |
| `config/brain.default.json` | 主脑默认提示词 |

