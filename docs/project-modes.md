# Conversation Mode

Conversation Mode 是发送对话时选择的主脑工作策略，不是项目的固有属性。Mode 名称
保持英文，界面和文档说明使用中文。

| Mode | 主脑行为 |
| --- | --- |
| `Manual` | 严格按用户明确指令规划，不主动扩展任务范围。 |
| `Edit Automatically` | 自动规划并执行完成目标所需的文件修改，但避免无关或高风险扩展。 |
| `Plan` | 只生成任务计划和 DAG，不启动执行 Agent。 |
| `Auto` | 自动规划、执行、验收，并在限制内自主返工。 |

内部值为 `manual`、`editAutomatically`、`plan` 和 `auto`。每次发送对话时，
前端把所选值随 `/api/runs` 请求提交；未提供时按 `auto` 处理。`project.yaml`
不保存 Mode。

## 与 DAG 和 Flow 的关系

Conversation Mode 不属于 Flow，也不改变 Flow 的定义：

- Conversation Mode 决定本轮主脑如何规划，以及生成计划后是否继续执行；
- DAG/Flow 决定任务依赖、并行、条件、循环和汇流；
- Agent 配置继续定义能力、Skill、工作目录和安全边界；DAG 节点仍可声明任务级
  `allowed_tools`。

`Plan` 模式会生成正常的 `plan.created` 事件和 DAG，但调度器直接进入结果汇总，
不会产生 `agent.started` 事件。其他模式继续使用现有 DAG/Flow 执行链路。

## Claude Agent SDK

Conversation Mode 不映射 Claude Agent SDK 的权限模式。所有 Claude Agent 节点统一使用：

```python
ClaudeAgentOptions(permission_mode="auto")
```

因此对话 Mode 只影响主脑，不会造成不同 Agent 使用不同 SDK 权限策略。运行时
`run.started` 和 `conversation.mode` 事件会记录本次运行选择的 Mode；
`agent.prompt` 会记录实际使用的 `sdk_permission_mode: auto`。
