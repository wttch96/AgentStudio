import type {
  AgentDetail,
  AgentProfile,
  BrainConfiguration,
  DeepSeekBalance,
  FlowDefinition,
  FlowTrace,
  Run,
  RunEvent,
  MemoryConfiguration,
  SchedulerConfiguration,
  SkillProfile,
  SystemStatus,
} from '../types'

// 开发环境默认走 Vite 的本机同源代理，避免 Safari/WebKit 把跨端口错误简化成
// 无法定位的 “Load failed”。仍可通过 VITE_API_BASE 显式覆盖。
const API_BASE = import.meta.env.VITE_API_BASE ?? '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: response.statusText }))
    throw new Error(body.error ?? `请求失败：${response.status}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  status: () => request<SystemStatus>('/status'),
  agents: async (projectId?: string) => {
    const p = projectId ? '?project_id=' + encodeURIComponent(projectId) : ''
    return (await request<{ items: AgentProfile[] }>('/agents' + p)).items
  },
  agent: (name: string, projectId?: string) => {
    const p = projectId ? '?project_id=' + encodeURIComponent(projectId) : ''
    return request<AgentDetail>(`/agents/${name}${p}`)
  },
  updateAgent: (name: string, payload: Omit<AgentDetail, 'name' | 'skill_count' | 'builtin'>) =>
    request<AgentDetail>(`/agents/${name}`, { method: 'PUT', body: JSON.stringify(payload) }),
  skills: async (projectId?: string) => {
    const p = projectId ? '?project_id=' + encodeURIComponent(projectId) : ''
    return (await request<{ items: SkillProfile[] }>('/skills' + p)).items
  },
  skill: (name: string, projectId?: string) => {
    const p = projectId ? '?project_id=' + encodeURIComponent(projectId) : ''
    return request<Required<SkillProfile>>(`/skills/${name}${p}`)
  },
  createSkill: (payload: Required<SkillProfile> & { project_id?: string }) =>
    request<Required<SkillProfile>>('/skills', { method: 'POST', body: JSON.stringify(payload) }),
  updateSkill: (name: string, payload: Omit<Required<SkillProfile>, 'name'>, projectId?: string) => {
    const p = projectId ? '?project_id=' + encodeURIComponent(projectId) : ''
    return request<Required<SkillProfile>>(`/skills/${name}${p}`, { method: 'PUT', body: JSON.stringify(payload) })
  },
  runs: async (projectId?: string) => {
    const p = projectId ? '?project_id=' + encodeURIComponent(projectId) : ''
    return (await request<{ items: Run[] }>('/runs' + p)).items
  },
  run: (id: string) => request<Run & { events: RunEvent[]; conversation_runs?: Array<Pick<Run, 'id' | 'objective' | 'status' | 'turn_index' | 'parent_run_id' | 'final_answer' | 'created_at'>> }>(`/runs/${id}`),
  conversation: (conversationId: string) => request<{ conversation_id: string; turn_count: number; runs: Array<Run & { events: RunEvent[] }> }>(`/conversations/${conversationId}`),
  deleteRun: async (id: string) => {
    const response = await fetch(`${API_BASE}/runs/${id}`, { method: 'DELETE' })
    if (!response.ok) {
      const body = await response.json().catch(() => ({ error: response.statusText }))
      throw new Error(body.error ?? `删除失败：${response.status}`)
    }
  },
  indexRunToKnowledge: (runId: string) =>
    request<{ id: string; indexed: boolean }>(`/runs/${runId}/index-to-knowledge`, { method: 'POST' }),
  workspace: () => request<{ path: string }>('/workspace'),
  updateWorkspace: (path: string) =>
    request<{ path: string }>('/workspace', { method: 'PUT', body: JSON.stringify({ path }) }),
  browseWorkspace: (path?: string) =>
    request<{ current: string; parent: string | null; directories: { name: string; path: string }[]; files: { name: string; path: string }[] }>(
      `/workspace/directories${path ? `?path=${encodeURIComponent(path)}` : ''}`,
    ),
  pickFolder: () =>
    request<{ path: string }>('/workspace/pick-folder', { method: 'POST' }),
  scheduler: () => request<SchedulerConfiguration>('/scheduler'),
  updateScheduler: (payload: SchedulerConfiguration) =>
    request<SchedulerConfiguration>('/scheduler', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  brain: () => request<BrainConfiguration>('/brain'),
  defaultBrain: () => request<BrainConfiguration>('/brain/default'),
  updateBrain: (payload: BrainConfiguration) =>
    request<BrainConfiguration>('/brain', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  deepseekBalance: (refresh = false) =>
    request<DeepSeekBalance>(`/deepseek/balance${refresh ? '?refresh=1' : ''}`),
  createRun: (objective: string, parentRunId?: string, projectId?: string) =>
    request<Run>('/runs', {
      method: 'POST',
      body: JSON.stringify({ objective, parent_run_id: parentRunId, project_id: projectId }),
    }),
  cancelRun: (id: string) => request<{ accepted: boolean }>(`/runs/${id}/cancel`, { method: 'POST' }),
  forkRun: (runId: string, objective?: string) =>
    request<Run & { fork_preview: Record<string, unknown> | null }>(`/runs/${runId}/fork`, {
      method: 'POST',
      body: JSON.stringify({ objective }),
    }),
  memoryConfig: () => request<MemoryConfiguration>('/memory'),
  updateMemoryConfig: (payload: MemoryConfiguration) =>
    request<MemoryConfiguration>('/memory', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  interruptRun: (runId: string, payload: {
    target: string
    action: string
    target_agent?: string
    target_task?: string
    target_node?: string
    instruction?: string
  }) =>
    request<{ id: string; accepted: boolean }>(`/runs/${runId}/interrupt`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  resumeRun: (runId: string, commandId: string, decision?: string) =>
    request<{ accepted: boolean }>(`/runs/${runId}/resume`, {
      method: 'POST',
      body: JSON.stringify({ command_id: commandId, decision: decision || 'apply' }),
    }),

  knowledgeSearch: (q: string, category?: string, topK?: number, projectId?: string) => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (category) params.set('category', category)
    if (topK) params.set('top_k', String(topK))
    if (projectId) params.set('project_id', projectId)
    return request<{ items: import('../types').KnowledgeEntry[] }>('/knowledge?' + params.toString())
  },
  knowledgeGet: (id: string) => request<import('../types').KnowledgeEntry>('/knowledge/' + id),
  knowledgeCreate: (payload: { title: string; content: string; category?: string; tags?: string[]; expires_at?: string | null }) =>
    request<{ id: string }>('/knowledge', { method: 'POST', body: JSON.stringify(payload) }),
  knowledgeUpdate: (id: string, payload: Record<string, unknown>) =>
    request<{ id: string }>('/knowledge/' + id, { method: 'PUT', body: JSON.stringify(payload) }),
  knowledgeDelete: (id: string) =>
    fetch(API_BASE + '/knowledge/' + id, { method: 'DELETE' }).then(r => { if (!r.ok) throw new Error('删除失败') }),
  knowledgeImport: (filepath: string, category?: string, projectId?: string) =>
    request<{ imported: number; total_blocks: number; entries: string[]; source: string }>('/knowledge/import', {
      method: 'POST',
      body: JSON.stringify({ filepath, category, project_id: projectId }),
    }),
  knowledgeFeedback: (id: string, feedback: 'up' | 'down') =>
    request<{ entry_id: string; score: number }>('/knowledge/' + id + '/feedback', { method: 'POST', body: JSON.stringify({ entry_id: id, feedback }) }),
  knowledgeRelations: (id: string) =>
    request<{ items: import('../types').KnowledgeRelation[] }>('/knowledge/' + id + '/relations'),
  knowledgeAddRelation: (payload: { source_id: string; target_id: string; relation_type: string }) =>
    request<{ id: string }>('/knowledge/relations', { method: 'POST', body: JSON.stringify(payload) }),
  knowledgeStats: (projectId?: string) => {
    const p = projectId ? '?project_id=' + encodeURIComponent(projectId) : ''
    return request<import('../types').KnowledgeStats>('/knowledge-stats' + p)
  },
  projects: () => request<{ items: import("../types").Project[] }>("/projects"),
  createProject: (name: string, root_dir: string, description?: string) =>
    request<import("../types").Project>("/projects", { method: "POST", body: JSON.stringify({ name, root_dir, description }) }),
  deleteProject: (id: string) =>
    fetch(API_BASE + "/projects/" + id, { method: "DELETE" }).then(r => { if (!r.ok) throw new Error("delete failed") }),
  setCurrentProject: (projectId: string) =>
    request<{ ok: boolean; project_id: string }>("/projects/current", { method: "PUT", body: JSON.stringify({ project_id: projectId }) }),
  getCurrentProject: () =>
    request<{ project_id: string }>("/projects/current"),
  projectAgents: (projectId: string) =>
    request<{ items: import("../types").ProjectAgent[] }>("/projects/" + projectId + "/agents"),
  addProjectAgent: (projectId: string, params: { template_id?: string; name?: string; display_name?: string; agent_type?: string; sub_dir?: string; system_prompt?: string; description?: string; tools?: string[]; skills?: string[]; model?: string }) =>
    request<import("../types").ProjectAgent>("/projects/" + projectId + "/agents", { method: "POST", body: JSON.stringify(params) }),
  updateProjectAgent: (projectId: string, agentId: string, updates: Record<string, unknown>) =>
    request<import("../types").ProjectAgent>("/projects/" + projectId + "/agents/" + agentId, { method: "PUT", body: JSON.stringify(updates) }),
  deleteProjectAgent: (projectId: string, agentId: string) =>
    fetch(API_BASE + "/projects/" + projectId + "/agents/" + agentId, { method: "DELETE" }).then(r => { if (!r.ok) throw new Error("delete failed") }),
  templates: (category?: string) => {
    const p = category ? "?category=" + encodeURIComponent(category) : ""
    return request<{ items: import("../types").AgentTemplate[] }>("/templates" + p)
  },
  createTemplate: (payload: import("../types").AgentTemplate) =>
    request<{ id: string }>("/templates", { method: "POST", body: JSON.stringify(payload) }),
  updateTemplate: (id: string, updates: Record<string, unknown>) =>
    request<import("../types").AgentTemplate>("/templates/" + id, { method: "PUT", body: JSON.stringify(updates) }),
  deleteTemplate: (id: string) =>
    fetch(API_BASE + "/templates/" + id, { method: "DELETE" }).then(r => { if (!r.ok) throw new Error("delete failed") }),
  templateCenter: () =>
    request<{ agents: import("../types").AgentTemplate[]; skills: import("../types").SkillTemplate[] }>("/template-center"),
  publishSkillTemplate: (payload: { name: string; display_name?: string; description?: string; content: string; category?: string }) =>
    request<{ id: string }>("/template-center/skills", { method: "POST", body: JSON.stringify(payload) }),
  streamUrl: (id: string, after: number) => API_BASE + '/runs/' + id + '/stream?after=' + after,

  // ---- Flow Engine ----
  flows: () => request<{ items: FlowDefinition[] }>('/flows'),
  flow: (name: string) => request<FlowDefinition>('/flows/' + name),
  createFlow: (name: string, yamlContent: string) =>
    request<FlowDefinition>('/flows', {
      method: 'POST',
      body: JSON.stringify({ name, yaml_content: yamlContent }),
    }),
  updateFlow: (name: string, yamlContent: string) =>
    request<FlowDefinition>('/flows/' + name, {
      method: 'PUT',
      body: JSON.stringify({ yaml_content: yamlContent }),
    }),
  deleteFlow: (name: string) =>
    fetch(API_BASE + '/flows/' + name, { method: 'DELETE' }).then(r => {
      if (!r.ok) throw new Error('删除失败')
    }),
  matchFlows: (q: string) =>
    request<{ items: Array<FlowDefinition & { score: number }> }>('/flows/matches?q=' + encodeURIComponent(q)),
  flowTraces: (runId: string) =>
    request<{ items: FlowTrace[] }>('/runs/' + runId + '/flow-traces'),

}
