import type {
  AgentDetail,
  AgentProfile,
  DeepSeekBalance,
  DeepSeekUsage,
  Run,
  RunEvent,
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
  agents: async () => (await request<{ items: AgentProfile[] }>('/agents')).items,
  agent: (name: string) => request<AgentDetail>(`/agents/${name}`),
  updateAgent: (name: string, payload: Omit<AgentDetail, 'name' | 'skill_count' | 'builtin'>) =>
    request<AgentDetail>(`/agents/${name}`, { method: 'PUT', body: JSON.stringify(payload) }),
  skills: async () => (await request<{ items: SkillProfile[] }>('/skills')).items,
  skill: (name: string) => request<Required<SkillProfile>>(`/skills/${name}`),
  createSkill: (payload: Required<SkillProfile>) =>
    request<Required<SkillProfile>>('/skills', { method: 'POST', body: JSON.stringify(payload) }),
  updateSkill: (name: string, payload: Omit<Required<SkillProfile>, 'name'>) =>
    request<Required<SkillProfile>>(`/skills/${name}`, { method: 'PUT', body: JSON.stringify(payload) }),
  runs: async () => (await request<{ items: Run[] }>('/runs')).items,
  run: (id: string) => request<Run & { events: RunEvent[] }>(`/runs/${id}`),
  deleteRun: async (id: string) => {
    const response = await fetch(`${API_BASE}/runs/${id}`, { method: 'DELETE' })
    if (!response.ok) {
      const body = await response.json().catch(() => ({ error: response.statusText }))
      throw new Error(body.error ?? `删除失败：${response.status}`)
    }
  },
  workspace: () => request<{ path: string }>('/workspace'),
  updateWorkspace: (path: string) =>
    request<{ path: string }>('/workspace', { method: 'PUT', body: JSON.stringify({ path }) }),
  browseWorkspace: (path?: string) =>
    request<{ current: string; parent: string | null; directories: { name: string; path: string }[] }>(
      `/workspace/directories${path ? `?path=${encodeURIComponent(path)}` : ''}`,
    ),
  scheduler: () => request<SchedulerConfiguration>('/scheduler'),
  updateScheduler: (payload: SchedulerConfiguration) =>
    request<SchedulerConfiguration>('/scheduler', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  deepseekBalance: (refresh = false) =>
    request<DeepSeekBalance>(`/deepseek/balance${refresh ? '?refresh=1' : ''}`),
  deepseekUsage: () => request<DeepSeekUsage>('/deepseek/usage'),
  createRun: (objective: string, parentRunId?: string) =>
    request<Run>('/runs', {
      method: 'POST',
      body: JSON.stringify({ objective, parent_run_id: parentRunId }),
    }),
  cancelRun: (id: string) => request<{ accepted: boolean }>(`/runs/${id}/cancel`, { method: 'POST' }),
  streamUrl: (id: string, after: number) => `${API_BASE}/runs/${id}/stream?after=${after}`,
}
