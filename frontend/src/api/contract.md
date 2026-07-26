# Agent Studio 前后端接口规范

> 版本: 1.0 | 协商日期: 2026-07-25 | 基准: 后端 `routes.py` + 前端 `client.ts` + `types.ts`
>
> 本文档为前后端协商一致后的最终接口规范，前后端双方均需遵守。前端写入范围: `frontend/`，后端写入范围: `backend/`。

---

## 通用约定

| 项目 | 约定 |
|------|------|
| **Base URL** | 前端通过 Vite 代理访问 `/api`，开发环境同源（避免跨端口错误）；可通过 `VITE_API_BASE` 覆盖 |
| **Content-Type** | `application/json`（SSE 流除外） |
| **认证** | 本地模式（`127.0.0.1`），无外部认证，通过 `GET /status` 验证可用性 |
| **SSE 流** | `GET /api/runs/{id}/stream`，`text/event-stream`，含 keep-alive 心跳（每 3s） |
| **错误格式** | `{ "error": "<message>" }` 或 `{ "error": "<message>", "details": [...] }`（Pydantic 校验错误） |
| **HTTP 方法语义** | GET=读取, POST=创建/动作, PUT=全量更新, DELETE=删除 |
| **空响应** | DELETE 成功返回 `204 No Content`，无 body |
| **标识符** | 所有 ID 使用 UUID hex（32 位小写十六进制） |

---

## 端点一览

### 1. 系统状态

#### `GET /api/status`

获取系统运行状态和配置信息。不返回任何密钥。

**Response** (200):
```json
{
  "demo_mode": false,
  "deepseek_configured": true,
  "claude_configured": false,
  "claude_route": "direct",
  "deepseek_model": "deepseek-chat",
  "claude_model": "claude-sonnet-4-20250514",
  "access": "local-only",
  "workspace_root": "/path/to/workspace"
}
```

**类型**: `SystemStatus`（前端 `types.ts`）

**协商确认**: 后端不返回 `workspace_root` 时前端以空字符串兜底。

---

### 2. Agent 管理

#### `GET /api/agents?project_id={id}`

获取 Agent 列表。`project_id` 为空时返回全局 Agent。

**Response** (200):
```json
{
  "items": [
    {
      "id": "abc123",
      "name": "code-reviewer",
      "display_name": "Code Reviewer",
      "description": "Reviews code changes",
      "skills": ["lint"],
      "skill_count": 1,
      "builtin": true,
      "sub_dir": "src",
      "project_id": "proj1",
      "agent_type": "claude"
    }
  ]
}
```

**类型**: `AgentProfile[]`（前端 `types.ts`）

#### `GET /api/agents/{name}?project_id={id}`

获取单个 Agent 详情（含 prompt）。`project_id` 必填。

**Response** (200):
```json
{
  "id": "abc123",
  "name": "code-reviewer",
  "display_name": "Code Reviewer",
  "description": "Reviews code changes",
  "prompt": "You are a code reviewer...",
  "skills": ["lint"],
  "skill_count": 1,
  "sub_dir": "src",
  "is_required": true,
  "agent_type": "claude"
}
```

**Errors**: 400（缺少 project_id）、404（Agent 不存在）

**协商确认**: 前端 `AgentDetail` 类型含 `skill_count` 和 `builtin`，后端 `/agents/{name}` 实际返回 `skill_count` 但不返回 `builtin`。前端需自行兼容缺失字段。

#### `PUT /api/agents/{name}` — 已弃用

返回 400，提示使用 `/api/projects/{id}/agents/{id}` 替代。

---

### 3. Skill 管理

#### `GET /api/skills?project_id={id}`

获取 Skill 列表。`project_id` 为空时返回全局 Skill。

**Response** (200): `{ "items": SkillProfile[] }`

**类型**: `SkillProfile` — `{ name, description, content? }`

#### `GET /api/skills/{name}?project_id={id}`

获取单个 Skill 详情。

**Response** (200): `SkillProfile`（含 `content`）

**Errors**: 404

#### `POST /api/skills`

创建 Skill。body 中 `project_id` 非空 → 项目级 Skill，空 → 全局 Skill。

**Request**:
```json
{
  "name": "my-skill",
  "description": "Skill description",
  "content": "Skill body text...",
  "project_id": "proj1"
}
```

**Response** (201): `SkillProfile`

**验证规则**: `name` 匹配 `^[a-z][a-z0-9-]{1,63}$`

**Errors**: 400（校验失败）、409（同名已存在）

#### `PUT /api/skills/{name}?project_id={id}`

更新 Skill。

**Request**: `{ "description": "...", "content": "..." }`

**Response** (200): `SkillProfile`

---

### 4. 工作空间

#### `GET /api/workspace`

获取当前工作空间根目录。

**Response** (200): `{ "path": "/path/to/workspace" }`

#### `PUT /api/workspace`

更改工作空间根目录。

**Request**: `{ "path": "/new/path" }`

**Response** (200): `{ "path": "/new/path" }`

#### `GET /api/workspace/directories?path={path}`

浏览工作空间目录。

**Response** (200):
```json
{
  "current": "/path/to/workspace",
  "parent": null,
  "directories": [{ "name": "src", "path": "/path/to/workspace/src" }],
  "files": [{ "name": "README.md", "path": "/path/to/workspace/README.md" }]
}
```

---

### 5. 调度配置

#### `GET /api/scheduler`

**Response** (200): `SchedulerConfiguration`

```json
{
  "max_concurrent_agents": 4,
  "recursion_limit": 100,
  "agent_max_turns": 30,
  "agent_timeout_seconds": 600
}
```

**字段约束**: `max_concurrent_agents` [1,8], `recursion_limit` [10,500], `agent_max_turns` [1,100], `agent_timeout_seconds` [30,7200]

#### `PUT /api/scheduler`

全量更新调度配置。body 同上。

---

### 6. 主脑配置

#### `GET /api/brain`

**Response** (200): `BrainConfiguration`

```json
{
  "orchestration_prompt": "You are the master brain..."
}
```

**字段约束**: `orchestration_prompt` 长度 [50, 50000]

#### `GET /api/brain/default`

获取内置默认主脑配置。

**Response** (200): `BrainConfiguration`

#### `PUT /api/brain`

全量更新主脑配置。body 同上。

---

### 7. DeepSeek 用量

#### `GET /api/deepseek/balance?refresh=0|1`

获取 DeepSeek 账户余额。`refresh=1` 强制刷新。

**Response** (200): `DeepSeekBalance`

```json
{
  "configured": true,
  "available": true,
  "infos": [{ "currency": "CNY", "total_balance": "100.00", "granted_balance": "50.00", "topped_up_balance": "50.00" }],
  "error": null
}
```

#### `GET /api/deepseek/usage`

获取 DeepSeek API 用量统计（本地估算）。

**Response** (200): `DeepSeekUsage`

```json
{
  "local": true,
  "estimated": true,
  "model": "deepseek-chat",
  "today": { "requests": 10, "prompt_tokens": 5000, "cache_hit_tokens": 1000, "cache_miss_tokens": 4000, "completion_tokens": 2000, "total_tokens": 7000, "estimated_cost_usd": "0.005", "first_recorded_at": "..." },
  "month": { ... },
  "all_time": { ... },
  "pricing_usd_per_million": { "cache_hit": 0.14, "cache_miss": 0.56, "output": 2.19 }
}
```

**协商确认**: 所有金额为本地估算（`local: true, estimated: true`），非实时 API 数据。前端应标注 "估算值"。

---

### 8. 任务运行

#### `POST /api/runs`

创建并启动一次运行。

**Request**:
```json
{
  "objective": "用户目标描述",
  "parent_run_id": null,
  "project_id": null
}
```

**字段约束**: `objective` [2, 20000] 字符

**Response** (202): `Run`

```json
{
  "id": "abc123",
  "objective": "...",
  "workspace_root": "/path",
  "parent_run_id": null,
  "conversation_id": "conv456",
  "turn_index": 0,
  "status": "queued",
  "final_answer": null,
  "error": null,
  "created_at": "2026-07-25T...",
  "updated_at": "2026-07-25T..."
}
```

**Errors**: 400（校验失败）、409（已有运行在执行）

#### `GET /api/runs`

列出所有运行记录。

**Response** (200): `{ "items": Run[] }`

#### `GET /api/runs/{id}`

获取单个运行详情（含事件和对话上下文）。

**Response** (200):
```json
{
  "id": "abc123",
  "objective": "...",
  "status": "completed",
  "events": [ ... ],
  "conversation_id": "conv456",
  "conversation_runs": [
    { "id": "...", "objective": "...", "status": "completed", "turn_index": 0, "parent_run_id": null, "final_answer": "...", "created_at": "..." }
  ]
}
```

`conversation_runs` 仅在 `conversation_id` 非空时出现。

**协商确认**: 前端 `Run` type 不含 `events` 和 `conversation_runs` 字段，它们由 `api.run()` 的返回类型扩展。调用方需自行处理。

#### `GET /api/conversations/{conversation_id}`

获取同一对话线程下所有 runs 及其 events，按 `turn_index` 排序。

**Response** (200):
```json
{
  "conversation_id": "conv456",
  "turn_count": 3,
  "runs": [
    { "id": "...", "objective": "...", "status": "completed", "turn_index": 0, "parent_run_id": null, "final_answer": "...", "error": null, "created_at": "...", "updated_at": "...", "events": [...] }
  ]
}
```

#### `DELETE /api/runs/{id}`

删除运行记录。正在执行的运行不可删除。

**Response**: 204（成功）、404（不存在）、409（仍在执行）

#### `POST /api/runs/{id}/cancel`

取消正在执行的运行。

**Response** (202/409): `{ "accepted": true|false }`

#### `POST /api/runs/{id}/fork`

从已完成的任务分叉，携带记忆上下文开启新对话分支。

**Request**: `{ "objective": "新目标（可选，默认沿用源目标）" }`

**Response** (202):
```json
{
  "id": "new-run-id",
  "...": "...",
  "fork_preview": {
    "sourceRunId": "...",
    "sourceObjective": "...",
    "turnCount": 3,
    "memoryStats": { ... },
    "recentMemories": [...]
  }
}
```

**约束**: 只能从 `completed`/`failed`/`cancelled` 状态分叉。

#### `GET /api/runs/{id}/events?after={sequence}`

获取运行事件列表（轮询模式）。

**Response** (200): `{ "items": RunEvent[] }`

#### `GET /api/runs/{id}/stream?after={sequence}`

SSE 流式获取运行事件。每 3 秒发送 keep-alive 心跳。

**Event format**:
```
id: 42
event: run-event
data: {"run_id":"...","sequence":42,"type":"agent_message","timestamp":"...","agent_id":"...","task_id":"...","payload":{...}}

: keep-alive
```

**协商确认**: 前端 `api.streamUrl()` 仅构造 URL，由组件自行建立 `EventSource` 连接。运行结束后流自动关闭。

---

### 9. 中断指令

#### `POST /api/runs/{id}/interrupt`

发送中断指令。

**Request**:
```json
{
  "target": "all",
  "action": "pause",
  "target_agent": null,
  "target_task": null,
  "instruction": ""
}
```

**字段**:
- `target`: `"all"` | `"agent"` | `"planner"` | `"task"`
- `action`: `"pause"` | `"inject"` | `"replan"` | `"abort"` | `"resume"`

**Response** (202): `{ "id": "cmd-id", "accepted": true }`

#### `POST /api/runs/{id}/resume`

恢复被中断的运行。

**Request**:
```json
{
  "command_id": "cmd-id",
  "decision": "apply"
}
```

`decision`: `"apply"` | `"discard"` | `"defer"`

**Response** (202): `{ "accepted": true }`

运行中的引导统一使用 `/brain <指令>` 或 `/<agent-name> <指令>`。节点详情只发送
`target: "task", action: "abort"`，不再提供第二套引导输入。

---

### 10. 记忆配置

#### `GET /api/memory`

**Response** (200): `MemoryConfiguration`

```json
{
  "compress_trigger_tokens": 8000,
  "compress_keep_recent": 20,
  "summarizer_model": "deepseek-v4-pro",
  "max_conversation_turns": 100,
  "session_archive_after_hours": 24,
  "importance_decay_rate": 0.95
}
```

**字段约束**:
| 字段 | 范围 |
|------|------|
| `compress_trigger_tokens` | [2000, 50000] |
| `compress_keep_recent` | [5, 50] |
| `max_conversation_turns` | [10, 1000] |
| `session_archive_after_hours` | [1, 720] |
| `importance_decay_rate` | [0.5, 1.0] |

#### `PUT /api/memory`

全量更新记忆配置。body 同上。

#### `GET /api/memory/stats/{conversation_id}`

获取对话的记忆统计。

**Response** (200): `MemoryStats`

```json
{
  "conversation_id": "conv456",
  "total_memories": 12,
  "memories_by_level": { "agent": 5, "planner": 3, "session": 2, "project": 2 },
  "total_tokens_saved": 50000,
  "compression_ratio": 0.65,
  "oldest_memory": "2026-07-24T...",
  "newest_memory": "2026-07-25T..."
}
```

---

### 11. 知识库

#### `GET /api/knowledge?q={query}&category={cat}&top_k={n}&project_id={id}`

搜索知识库。`q` 为空时列出全部条目。

**Response** (200): `{ "items": KnowledgeEntry[] }`

**类型** `KnowledgeEntry`:
```typescript
{
  id: string
  title: string
  content: string
  category: string
  tags: string[]
  source: string
  source_type: string       // "manual" | "import" | "auto"
  score: number
  created_at: string
  expires_at: string | null
  updated_at: string
  relations?: KnowledgeRelation[]
}
```

#### `GET /api/knowledge/{id}`

获取单条知识（含关联）。

**Response** (200): `KnowledgeEntry` (含 `relations` 字段)

#### `POST /api/knowledge`

创建知识条目。

**Request**:
```json
{
  "title": "标题",
  "content": "正文内容",
  "category": "general",
  "tags": ["tag1"],
  "source": "",
  "expires_at": null,
  "project_id": ""
}
```

**Response** (201): `{ "id": "entry-id" }`

#### `PUT /api/knowledge/{id}`

更新知识条目（部分字段）。

**Request**: `{ "title": "...", "content": "...", ... }`

**Response** (200): `{ "id": "entry-id" }`

#### `DELETE /api/knowledge/{id}`

删除知识条目。Response: 204

#### `POST /api/knowledge/import`

从工作区文件批量导入知识。

**Request**: `{ "filepath": "/path/to/file.md", "category": "docs", "project_id": "" }`

**Response** (201):
```json
{
  "imported": 5,
  "total_blocks": 5,
  "entries": ["id1", "id2", ...],
  "source": "/path/to/file.md"
}
```

#### `GET /api/knowledge/{id}/relations`

获取知识条目的所有关联。

**Response** (200): `{ "items": KnowledgeRelation[] }`

#### `POST /api/knowledge/relations`

创建知识关联。

**Request**: `{ "source_id": "id1", "target_id": "id2", "relation_type": "related" }`

**Response** (201): `{ "id": "rel-id" }`

#### `POST /api/knowledge/{id}/feedback`

提交知识反馈。

**Request**: `{ "entry_id": "id", "feedback": "up" }`  — `feedback`: `"up"` | `"down"`

**Response** (200): `{ "entry_id": "id", "score": 1 }`

#### `GET /api/knowledge-stats?project_id={id}`

知识库统计。

**Response** (200): `KnowledgeStats` — `{ total, by_category, expired, relations }`

#### `POST /api/knowledge/cleanup`

清理过期知识条目。**无 body**。

**Response** (200): `{ "cleaned": 3 }`

**协商确认**: 前端 `api.knowledgeStats()` 调用此端点，`api.knowledgeCreate()` 不传 `project_id`。`KnowledgeEntry` 的 `source_type` 字段为前端独有推断（后端不返回，前端从 `source` 推导）。

---

### 12. 项目管理

#### `GET /api/projects`

列出所有项目。

**Response** (200): `{ "items": Project[] }`

#### `POST /api/projects`

创建项目。

**Request**:
```json
{
  "name": "My Project",
  "project_name": "my-project",
  "root_dir": "/path/to/project",
  "description": "Project description",
  "mode": "auto"
}
```

`project_name` 可选，但建议显式提供；它是 `.workspace/<project_name>/`
的稳定目录名，只允许小写字母、数字和连字符。

**Response** (201): `Project`

`mode` 可选值：`manual`、`editAutomatically`、`plan`、`auto`；不传时默认为
`auto`。

#### `GET /api/projects/{id}`

获取项目详情。

**Response** (200): `Project`（不含 `updated_at` — 后端 `Project` 模型无此字段，但前端类型含此字段）

**协商确认**: 后端 `Project` 模型无 `updated_at` 字段，前端类型声明了该字段。前端调用方需处理其可能为 `undefined` 的情况。

#### `PUT /api/projects/{id}`

更新项目名称、描述或 Project Mode。

```json
{ "mode": "plan" }
```

#### `DELETE /api/projects/{id}`

删除项目。Response: 204

#### `GET/PUT /api/projects/current`

读取或设置 `.workspace/current-project.yaml`。切换后，后续请求使用目标项目
自己的配置、SQLite、RAG、记忆和 checkpoint。

#### `GET /api/projects/{id}/agents`

列出项目下的 Agent。

**Response** (200): `{ "items": ProjectAgent[] }`

#### `POST /api/projects/{id}/agents`

向项目添加 Agent（从模板创建）。

**Request**:
```json
{
  "template_id": "tpl-id",
  "sub_dir": "src",
  "system_prompt": "Custom prompt...",
  "display_name": "My Agent"
}
```

**Response** (201): `ProjectAgent`

#### `PUT /api/projects/{id}/agents/{agent_id}`

更新项目 Agent 配置。

**Request**: 部分字段 JSON，支持 `role`、`sub_dir`、`system_prompt`、
`capabilities`、`limitations`、`preferred_tasks`、`forbidden_tasks`、
`skills`、输入/输出契约、`priority` 和 `max_iterations`。Agent 不再配置预批准
工具；关联 Skill 后即可由执行器加载。

**Response** (200): `ProjectAgent`

#### `DELETE /api/projects/{id}/agents/{agent_id}`

移除项目 Agent。Response: 204

---

### 13. 模板管理

#### `GET /api/templates?category={cat}`

列出模板。

**Response** (200): `{ "items": AgentTemplate[] }`

#### `POST /api/templates`

创建模板。

**Request**: `AgentTemplate`（全量字段）

**Response** (201): `{ "id": "tpl-id" }`

#### `PUT /api/templates/{id}`

更新模板（部分字段）。

**Response** (200): `AgentTemplate`

#### `DELETE /api/templates/{id}`

删除非内置模板。Response: 204

---

### 14. 模板中心

#### `GET /api/template-center`

获取所有 Agent 模板和 Skill 模板。

**Response** (200):
```json
{
  "agents": [ AgentTemplate, ... ],
  "skills": [ SkillTemplate, ... ]
}
```

#### `POST /api/template-center/skills`

将项目 Skill 发布为公共 Skill 模板。

**Request**:
```json
{
  "name": "my-skill",
  "display_name": "My Skill",
  "description": "Description",
  "content": "Skill body...",
  "category": "general"
}
```

**Response** (201): `{ "id": "skill-tpl-id" }`

---

## 前后端协商结果摘要

| # | 议题 | 结果 |
|---|------|------|
| 1 | **Agent 更新路由** | 后端 `/api/agents/{name}` PUT 已弃用，统一使用 `/api/projects/{id}/agents/{id}` PUT。前端 `api.updateAgent()` 保留但实际不再被调用。 |
| 2 | **Agent 详情字段** | 后端 `/api/agents/{name}` 返回 `skill_count`、`is_required`，不返回 `builtin`。前端 `AgentDetail` 类型中的 `builtin` 字段后端不承诺返回，前端需兼容缺失。 |
| 3 | **Project.updated_at** | 后端 `Project` 模型无 `updated_at` 字段，前端类型已声明。约定：前端使用 `created_at` 作为时间参考，`updated_at` 取 `undefined` 时隐藏显示。 |
| 4 | **KnowledgeEntry.source_type** | 后端不返回 `source_type` 字段，前端类型中包含。约定：前端根据 `source` 字段自行推导（`""` → `"manual"`，路径 → `"import"`，以 `auto:` 开头 → `"auto"`）。 |
| 5 | **SSE 流** | `GET /api/runs/{id}/stream` 使用 `text/event-stream`，每 15 个空闲轮询周期（约 3s）发送 keep-alive 注释。前端使用 `EventSource` 连接。 |
| 6 | **DELETE 空响应** | 所有 DELETE 端点成功时返回 `204 No Content`。前端对 DELETE 使用裸 `fetch`，不调用 `request<T>()`（避免 JSON 解析失败）。 |
| 7 | **运行并发控制** | `POST /api/runs` 当前仅允许单个运行（已有运行在执行时返回 409）。未来可扩展为按项目隔离的并发控制。 |
| 8 | **分叉约束** | Fork 仅允许从终态（`completed`/`failed`/`cancelled`）分叉，`fork_preview` 提供记忆预览。前端可选择展示预览信息。 |
| 9 | **记忆统计** | `GET /api/memory/stats/{conversation_id}` 为独立端点。前端可在 Fork 预览或对话详情中调用。 |
| 10 | **接口文档存放** | 最终规范写入 `frontend/src/api/contract.md`（前端副本）和项目根目录共享文档。后端可在 `docs/` 目录存放引用或独立副本。 |

---

## 类型对照速查

| 领域 | 后端 Pydantic 模型 | 前端 TypeScript 接口 | 文件 |
|------|-------------------|---------------------|------|
| 任务运行 | `CreateRunRequest`, Run(字典) | `Run` | `models.py` / `types.ts` |
| 运行事件 | `RunEvent` | `RunEvent` | `models.py` / `types.ts` |
| Agent 列表 | 字典（`registry.list_public`） | `AgentProfile` | — / `types.ts` |
| Agent 详情 | 字典（`registry.load_project_agents`） | `AgentDetail` | — / `types.ts` |
| Skill | `SkillCreate`, `SkillUpdate` | `SkillProfile` | `configuration.py` / `types.ts` |
| 主脑配置 | `BrainConfiguration` | `BrainConfiguration` | `configuration.py` / `types.ts` |
| 调度配置 | `SchedulerConfiguration` | `SchedulerConfiguration` | `configuration.py` / `types.ts` |
| 记忆配置 | `MemoryConfiguration` | `MemoryConfiguration` | `configuration.py` / `types.ts` |
| 中断指令 | `InterruptCommand` | `InterruptCommand` | `models.py` / `types.ts` |
| 知识条目 | `KnowledgeEntry` | `KnowledgeEntry` | `models.py` / `types.ts` |
| 知识关联 | `KnowledgeRelation` | `KnowledgeRelation` | `models.py` / `types.ts` |
| 项目 | `Project` | `Project` | `models.py` / `types.ts` |
| 项目 Agent | `ProjectAgent` | `ProjectAgent` | `models.py` / `types.ts` |
| Agent 模板 | `AgentTemplate` | `AgentTemplate` | `models.py` / `types.ts` |
| 余额 | — | `DeepSeekBalance` | `types.ts` |
| 用量 | — | `DeepSeekUsage` | `types.ts` |
| DAG 任务 | `DagTask`, `TaskDag` | `PlanTask` | `models.py` / `types.ts` |
| Agent 结果 | `AgentResult` | `AgentResult` | `models.py` / `types.ts` |
| 工作空间 | `WorkspaceUpdate` | — | `configuration.py` |

---

## 变更记录

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-07-25 | 1.0 | 初始版本，基于后端 `routes.py` + 前端 `client.ts` + `types.ts` 对齐生成 |
