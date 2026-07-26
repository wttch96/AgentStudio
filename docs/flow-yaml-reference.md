# Flow YAML 参考

```yaml
name: feature-delivery
version: "1.1"
description: 功能交付流程
keywords: [功能开发, feature]

nodes:
  - id: inspect
    agent: code-reviewer
    title: 分析现状
    objective: "分析 {{ input.requirement }}"
    write_scope: []
    timeout_seconds: 300
    max_turns: 8
    interruptible: true
    retry_on_failure: false
    depends_on: []

  - id: frontend
    agent: vue-frontend
    title: 前端实现
    objective: "根据 {{ inspect.output.summary }} 实现前端"
    write_scope: [frontend/]
    depends_on: [inspect]

  - id: backend
    agent: flask-backend
    title: 后端实现
    objective: "根据 {{ inspect.output.summary }} 实现后端"
    write_scope: [backend/]
    depends_on: [inspect]

conditions:
  - id: quality-gate
    condition: "blackboard.review_score >= 0.8"
    then_branch: publish
    else_branch: fix

parallels:
  - id: implementation
    items: [frontend, backend]
    max_concurrency: 2

loops:
  - id: repair-loop
    condition: "blackboard.review_score < 0.8"
    body: fix
    max_iterations: 3

steps: [inspect, implementation, quality-gate, repair-loop, publish]

synthesize:
  template: |
    已完成 {{ results | length }} 个节点。
```

## 字段

### nodes

`agent` 必须是当前项目 Agent；`objective` 支持 Jinja2；`write_scope` 为空表示只读。
`timeout_seconds`、`max_turns` 和 `interruptible` 是节点级运行限制。`depends_on`
定义数据依赖，只有依赖成功后节点才可运行。

### conditions

`condition` 从输入、Blackboard 和已完成节点结果中求值。`then_branch` 必填，
`else_branch` 可选。
分支目标必须引用已声明节点或块。

### parallels

`items` 同时执行，全部达到终态后汇流。存在重叠写入范围时调度器自动顺序化冲突节点。

### loops

循环体每次执行后重新求值 `condition`，并受 `max_iterations` 硬限制。

### steps

扩展流程的顶层控制顺序。条件、并行和循环块都必须通过其 ID 引用。

## 模板变量

- `input.<name>`：调用 Flow 时提供的输入
- `<node-id>.output.summary`：上游节点摘要
- `blackboard.<key>`：共享黑板值
- `results.<node-id>.status`：条件表达式中的已完成节点状态
- `results`：最终节点结果映射

所有引用在保存时校验。运行时缺失必需变量会使节点失败，而不是使用猜测值。

## 业务示例

`templates/project/flows/refund-review.yaml` 展示退款审核流程：

1. 受理退款申请。
2. 并行执行退款政策核查与订单履约核查。
3. `refund_amount <= 500` 且 `risk_level == "low"` 时进入自动退款决定，
   否则进入人工复核工单。
4. 两个分支最终汇总为退款审核报告。

手动执行时可传入：

```json
{
  "objective": "审核订单 ORD-20260726-001 的退款",
  "inputs": {
    "order_id": "ORD-20260726-001",
    "refund_amount": 299,
    "risk_level": "low",
    "reason": "商品破损"
  }
}
```
