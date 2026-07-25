export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'timeout' | 'interrupted'

export interface Run {
  id: string
  objective: string
  workspace_root: string | null
  parent_run_id: string | null
  conversation_id: string
  turn_index: number
  status: RunStatus
  final_answer: string | null
  error: string | null
  created_at: string
  updated_at: string
  started_at?: string | null
  project_id?: string
  forked_from_run_id?: string
}

export interface RunEvent {
  run_id: string
  sequence: number
  type: string
  timestamp: string
  agent_id: string | null
  task_id: string | null
  payload: Record<string, unknown>
}

export interface AgentProfile {
  id: string
  name: string
  display_name?: string
  description: string
  tools: string[]
  skills: string[]
  skill_count: number
  builtin: boolean
  sub_dir?: string
  project_id?: string
  agent_type?: 'claude' | 'rag' | 'file-ops'
}

export interface AgentDetail extends AgentProfile {
  prompt: string
}

export interface SkillProfile {
  name: string
  description: string
  content?: string
}

export interface SystemStatus {
  demo_mode: boolean
  deepseek_configured: boolean
  claude_configured: boolean
  claude_route: 'direct' | 'custom' | 'cc-switch'
  deepseek_model: string
  claude_model: string
  access: string
  workspace_root: string
}

export interface SchedulerConfiguration {
  max_concurrent_agents: number
  recursion_limit: number
  agent_max_turns: number
  agent_timeout_seconds: number
}

export interface BrainConfiguration {
  orchestration_prompt: string
}

export interface DeepSeekBalance {
  configured: boolean
  available: boolean
  infos: Array<{
    currency: string
    total_balance: string
    granted_balance: string
    topped_up_balance: string
  }>
  error: string | null
}

export interface PlanTask {
  id: string
  title: string
  objective: string
  agent: string
  depends_on: string[]
  write_scope: string[]
}

export interface AgentResult {
  task_id: string
  agent: string
  status: 'completed' | 'failed' | 'cancelled' | 'skipped'
  summary: string
  changed_files: string[]
  provides?: string[]
  error: string | null
  started_at: string | null
  duration_ms: number | null
}


// ==================== 执行图节点类型 ====================

/** 节点状态：PENDING → RUNNING → SUCCEEDED/FAILED/CANCELLED/INTERRUPTED/TIMEOUT */
export type NodeStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'timeout' | 'interrupted'

/** 节点类型：ORCHESTRATOR=主脑编排, AGENT=执行Agent */
export type NodeType = 'orchestrator' | 'agent'

/** 工具调用状态 */
export type ToolCallStatus = 'pending' | 'running' | 'completed' | 'failed'

/** 错误分类 */
export type ErrorType = 'EXCEPTION' | 'TIMEOUT' | 'USER_CANCEL' | 'UNKNOWN'

/** 中间步骤类型 */
export type StepType = 'thought' | 'action' | 'observation' | 'message'

/** 错误信息 */
export interface TaskError {
  nodeId: string
  type: ErrorType
  message: string
  stack: string | null  // 待后端补充：结构化堆栈跟踪
}

/** 单次工具调用 */
export interface ToolCall {
  id: string
  toolName: string
  input: Record<string, unknown>
  output: string | null   // 待后端补充: tool.completed 事件数据
  status: ToolCallStatus  // 待后端补充: tool.completed/failed 事件
  startedAt: string
  finishedAt: string | null
  durationMs: number | null  // 待后端补充: 工具调用耗时
  error: string | null
}

/** 工具调用分组（连续同名工具自动折叠） */
export interface ToolCallGroup {
  key: string
  toolName: string
  calls: ToolCall[]
  count: number
  collapsed: boolean
}

/** 中间推理步骤 */
export interface IntermediateStep {
  id: string
  type: StepType
  content: string
  timestamp: string
  sequence: number
  action?: {
    tool: string
    input: Record<string, unknown>
  }
}

/** 执行图节点（Canvas + DetailPanel 的核心数据模型） */
export interface ExecutionNode {
  id: string
  type: NodeType
  name: string                    // Agent 名称 或 "主脑编排"
  sub: string                     // 副标题 (任务标题/目标摘要)
  status: NodeStatus
  parentId: string | null
  agentId: string | null
  taskId: string | null
  runId: string
  depth: number                   // 依赖深度 (用于布局)
  startedAt: string | null
  finishedAt: string | null
  durationMs: number | null
  objective: string | null        // 任务目标 (task 节点)
  summary: string | null          // Agent 输出摘要
  input: Record<string, unknown> | null   // 节点输入
  output: Record<string, unknown> | null  // 节点输出
  error: TaskError | null
  hasError: boolean
  hasToolCalls: boolean
  toolCallCount: number
  intermediateSteps: IntermediateStep[]
  toolCallGroups: ToolCallGroup[]
  dependsOn: string[]             // 前置节点 ID 列表
  interruptible: boolean          // 是否允许中断
}

/** 节点依赖边 (Canvas 渲染用) */
export interface NodeEdge {
  from: string
  to: string
  label?: string
}

/** 超时状态 */
export interface TimeoutState {
  nodeId: string
  startedAt: string
  thresholdMs: number
  elapsedMs: number
  isTimedOut: boolean
}

/** 中断请求状态 */
export interface PendingInterrupt {
  id: string
  runId: string
  targetNodeId: string | null
  targetAgent: string | null
  action: 'pause' | 'inject' | 'abort'
  instruction: string
  createdAt: string
  status: 'pending' | 'sent' | 'applied' | 'rejected'
}

// ==================== 记忆系统类型 ====================

export interface MemoryRecord {
  id: string
  run_id: string
  conversation_id: string
  level: 'agent' | 'planner' | 'session' | 'project'
  agent_id: string | null
  task_id: string | null
  phase: string
  summary: string
  structured_data: Record<string, unknown> | null
  token_count_before: number
  token_count_after: number
  created_at: string
  importance: number
}

export interface MemoryConfiguration {
  compress_trigger_tokens: number
  compress_keep_recent: number
  summarizer_model: string
  max_conversation_turns: number
  session_archive_after_hours: number
  importance_decay_rate: number
}

export interface MemoryStats {
  conversation_id: string
  total_memories: number
  memories_by_level: Record<string, number>
  total_tokens_saved: number
  compression_ratio: number
  oldest_memory: string | null
  newest_memory: string | null
}

// ==================== 中断机制类型 ====================

export interface InterruptCommand {
  id: string
  run_id: string
  target: 'all' | 'agent' | 'planner'
  action: 'pause' | 'inject' | 'replan' | 'abort' | 'resume'
  target_agent: string | null
  target_task: string | null
  instruction: string
  created_at: string
}


// ==================== 对话与思考流程类型 ====================

export interface MemoryCompactionRecord {
  wave: number
  agentsCompacted: string[]
  tokenCountBefore: number | null
  tokenCountAfter: number | null
  timestamp: string
}

export interface ConversationTurn {
  id: string
  runId: string
  userMessage: string
  brainResponse: string | null
  thinkingText: string | null
  status: 'thinking' | 'executing' | 'responding' | 'complete' | 'error'
  planTasks: PlanTask[]
  waveCount: number
  memoryEvents: MemoryCompactionRecord[]
  createdAt: string
  completedAt: string | null
}

export interface StreamingState {
  activeTurnId: string | null
  thinkingText: string
  responseText: string
  isStreaming: boolean
}

export type UnifiedDagNodeType = 'conversation' | 'plan' | 'task' | 'memory' | 'synthesis'

export interface UnifiedDagNode {
  id: string
  type: UnifiedDagNodeType
  label: string
  sub: string
  depth: number
  x: number
  y: number
  w: number
  h: number
  status: string
  isStart?: boolean
  isEnd?: boolean
  task?: PlanTask
  conversationTurn?: ConversationTurn
  memoryRecord?: MemoryCompactionRecord
  expandable: boolean
}

export interface ActiveAgent {
  name: string
  taskId: string
  title: string
  status: 'running' | 'completed' | 'failed'
  startedAt: string | null
}

// ==================== Fork 类型 ====================

export interface ForkPreview {
  sourceRunId: string
  sourceObjective: string
  turnCount: number
  memoryStats: MemoryStats
  recentMemories: Array<{ phase: string; summary: string }>
}


// ==================== 知识库类型 ====================

export interface KnowledgeEntry {
  id: string
  title: string
  content: string
  category: string
  tags: string[]
  source: string
  source_type: string  // "manual" | "import" | "auto"
  score: number
  created_at: string
  expires_at: string | null
  updated_at: string
  relations?: KnowledgeRelation[]
  _rrf_score?: number
}

export interface KnowledgeRelation {
  id?: string
  source_id: string
  target_id: string
  relation_type: string
  created_at?: string
}

export interface KnowledgeStats {
  total: number
  by_category: Record<string, number>
  expired: number
  relations: number
}


// ==================== 多项目类型 ====================

export interface Project {
  id: string
  name: string
  root_dir: string
  description: string
  created_at: string
  updated_at: string
}

export interface ProjectAgent {
  id: string
  project_id: string
  name: string
  display_name: string
  description: string
  template_id: string | null
  agent_type: 'brain' | 'rag' | 'claude' | 'file-ops'
  sub_dir: string
  system_prompt: string
  tools: string[]
  skills: string[]
  is_required: boolean
  sort_order: number
}

export interface AgentTemplate {
  id: string
  name: string
  display_name: string
  description: string
  category: string
  agent_type: string
  default_sub_dir: string
  default_prompt: string
  default_tools: string[]
  default_skills: string[]
  is_builtin: boolean
}

export interface SkillTemplate {
  id: string
  name: string
  display_name: string
  description: string
  category: string
  content: string
  is_builtin: boolean
  created_at: string
}

// ==================== 流程编排 (Flow Engine) ====================

export interface FlowNode {
  id: string
  agent: string
  title: string
  objective: string  // Jinja2 template
  write_scope: string[]
  timeout_seconds: number
  max_turns: number
  interruptible: boolean
  retry_on_failure: boolean
  depends_on: string[]
}

export interface FlowDefinition {
  name: string
  description: string
  version: string
  keywords: string[]
  nodes: FlowNode[]
  synthesize?: { template: string }
  node_count?: number  // computed, from API
}

export interface FlowTrace {
  run_id: string
  node_id: string
  sequence: number
  rendered_prompt: string
  inputs_json: string
  outputs_json: string | null
  result_status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  started_at: string | null
  completed_at: string | null
  duration_ms: number | null
}
