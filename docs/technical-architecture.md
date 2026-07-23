# Agent Studio 技术架构

> 使用说明见 [README](../README.md)。

## 系统架构

```
Frontend (Vue 3 + TS) ←→ Flask API ←→ ServiceContainer (DI)
                                        ├─ DeepSeekPlanner (编排)
                                        ├─ ClaudeAgentExecutor (Claude Agent SDK)
                                        ├─ DeepSeekAgentExecutor (LangChain)
                                        ├─ RAGAgentExecutor (LangChain + KnowledgeStore)
                                        ├─ MemoryManager (LangMem)
                                        ├─ ProjectManager + KnowledgeStore
                                        └─ SQLiteStore
                                            ↓
                                     LangGraph Graph
```

## Agent 类型与执行器

| agent_type | Executor | 运行时 | 工具 |
|------------|----------|--------|------|
| `brain` | DeepSeek API 直接调用 | plan 节点 | DAG 编排 |
| `claude` | ClaudeAgentExecutor | worker 节点 | Read/Write/Edit/Glob/Grep/Bash/Skill |
| `deepseek` | DeepSeekAgentExecutor | worker 节点 | 同上 (LangChain `create_agent`) |
| `rag` | RAGAgentExecutor | worker 节点 | search/get/add/list_knowledge |

Graph worker 按 `agent_type` 分发到对应 executor。

## 执行流

```
START → plan → interrupt_check → scheduler → [worker×N] → barrier → compact_memory
                                                                    ↓
                                          replan_after_discovery ←─┘  (discovery)
                                                                    ↓
                                          interrupt_check → scheduler → [worker×N]
                                                                    ↓
                                          barrier → compact_memory → ...  
                                                                    ↓
                                          synthesize → extract_memory → END
```

- **plan**: 主脑分析目标，生成发现 DAG 或直接进入执行
- **interrupt_check**: 每轮检查中断指令；`inject` 类型直接注入 guidance 不暂停
- **scheduler**: 冻结本轮就绪任务集
- **worker**: Send 并行分发到对应 executor
- **barrier**: 本轮汇流
- **compact_memory**: 滑动窗口压缩
- **extract_memory**: LangMem 长期提取
- **synthesize**: 拼接 Agent 结果（不调 LLM）

## 记忆系统

| 层 | 节点 | 技术 |
|----|------|------|
| 短期 | `compact_memory` | SqliteSaver + 滑动窗口 + LLM 摘要 |
| 长期 | `extract_memory` | LangMem MemoryStoreManager |
| 策略 | StrategyEngine | 配置驱动：token 阈值/轮次/闲置 |

## 中断与引导

- `POST /runs/{id}/interrupt {action:"inject", instruction:"..."}` → 不暂停，注入 guidance
- `action:"pause"` → LangGraph `interrupt()` 挂起，`Command(resume=...)` 恢复
- 前端运行中输入 → 自动发送 inject 中断

## 多项目隔离

- 项目独立 Agent/Skill/知识库 (`project_id` 外键)
- 主脑/记忆/调度为全局配置
- Agent 注册表按项目缓存

## 数据存储

单 SQLite (`instance/agents-manager.db`), WAL 模式。

| 表 | 用途 |
|----|------|
| runs / events | 任务运行与事件流 |
| projects / project_agents | 多项目 + Agent |
| agent_templates / skill_templates | 模板中心 |
| project_skills | 项目 Skill |
| knowledge_entries / knowledge_fts | 知识库 + FTS5 |
| memories / session_summaries / *_memory_state | 分层记忆 |
| configs | KV 配置 |
| deepseek_usage | DeepSeek 用量 |
| interrupt_commands | 中断队列 |

## Token 追踪

- `agent.usage` 事件携带 `input_tokens`/`output_tokens`
- Claude Agent SDK `ResultMessage.usage` 原始数据透传
- 前端 AgentInspector 按 agent 独立汇总显示

## 关键依赖

- **LangGraph**: DAG 调度、Send 并行、SqliteSaver、interrupt
- **LangMem**: MemoryStoreManager、ThreadExtractor
- **Claude Agent SDK**: `query()` + `ClaudeAgentOptions`
- **LangChain**: `create_agent()` + `ChatOpenAI`
- **Flask + SSE**: REST + 事件流
- **SQLite**: FTS5 + 触发器
