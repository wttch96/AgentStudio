# Agent Studio 项目数据模板

此目录对应 `.workspace/<project_name>/` 的内容，不复制到用户代码目录。

```text
.workspace/<project_name>/
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

启用的项目由 `.workspace/current-project.yaml` 指定：

```yaml
project_id: my-project
```

`project_id` 同时是项目数据目录名，只允许小写字母、数字和连字符。

模板中的 `agents/`、`skills/` 和 `brain.yaml` 已包含统一协作、结构化结果、看板、
验收、Flow 与安全文件操作规则。`flows/` 保存项目自己的流程；全局
`templates/flows/` 仅作为创建项目时的种子。

各 Agent、Skill 的职责、挂载关系和源文件链接见
[Agent 与 Skill 模版](../../docs/agent-skill-templates.md)。
