# Flow 管理

Flow 是项目级、可复用、可验证的执行流程。项目 Flow 保存在
`.workspace/<project_name>/flows/*.yaml`；`templates/flows/` 只提供新项目的初始模板。

## 生命周期

1. 在 Flow 管理页创建或编辑 YAML。
2. 后端使用 `FlowDefinition` 校验节点引用、条件分支、循环和并行块。
3. 主脑收到目标后匹配项目 Flow；匹配成功时产生 `flow_invocation`，否则生成普通 DAG。
4. Flow 输入经过模板渲染后交给节点 Agent。
5. 节点状态、结果、产物、决策和阻塞同步写入 Todo 与 Blackboard。
6. 汇流节点生成最终输出，运行轨迹保存在项目数据库。

Flow 可以在管理页手动运行。手动运行使用
`POST /api/flows/{name}/runs`，不使用隐藏的斜杠命令。

## 可视化约定

![包含并行检查与条件分支的退款审核 Flow](images/flow-control.jpg)

- 矩形：Agent 执行节点
- 菱形：条件判断
- 并行网关：同时启动多个节点并等待汇流
- 回环曲线：循环体重新执行
- 实线箭头：依赖或控制流
- 边标签：`true`、`false`、`parallel`、`repeat`

运行中的节点可以独立中断。中断节点会标记为 `cancelled`，依赖它的下游任务进入
`blocked`，不会被误标记为完成。

## 主脑选择规则

只有当用户目标匹配 Flow 关键词、必需输入可构造、引用的 Agent 均存在且执行不会违反
当前约束时，主脑才选择 Flow。无法满足任一条件时回退到普通任务 DAG。
