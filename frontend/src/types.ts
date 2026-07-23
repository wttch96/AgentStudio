export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'

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
  name: string
  description: string
  tools: string[]
  skills: string[]
  skill_count: number
  builtin: boolean
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
  planning_prompt: string
  summary_prompt: string
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

export interface DeepSeekUsagePeriod {
  requests: number
  prompt_tokens: number
  cache_hit_tokens: number
  cache_miss_tokens: number
  completion_tokens: number
  total_tokens: number
  estimated_cost_usd: string
  first_recorded_at: string | null
}

export interface DeepSeekUsage {
  local: true
  estimated: true
  model: string
  today: DeepSeekUsagePeriod
  month: DeepSeekUsagePeriod
  all_time: DeepSeekUsagePeriod
  pricing_usd_per_million: {
    cache_hit: number
    cache_miss: number
    output: number
  }
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
  agent_sliding_window: number
  planner_sliding_window: number
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
