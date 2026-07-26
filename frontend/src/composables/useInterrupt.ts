import { reactive, type Ref } from 'vue'
import { api } from '../api/client'
import type { PendingInterrupt, Run, RunEvent } from '../types'

interface InterruptState {
  pendingInterrupts: PendingInterrupt[]
  /** 当前中断状态：idle | pending | applied */
  status: 'idle' | 'pending' | 'applied'
  /** 暂停后显示的引导输入模式 */
  guidanceMode: boolean
  guidanceTarget: string | null  // agent name or 'all'
}

/**
 * 中断命令状态管理。
 * 封装 interruptRun/resume 调用，追踪中断生命周期。
 */
export function useInterrupt(activeRun: Ref<Run | null>) {
  const state = reactive<InterruptState>({
    pendingInterrupts: [],
    status: 'idle',
    guidanceMode: false,
    guidanceTarget: null,
  })

  /**
   * 发送中断命令
   */
  async function sendInterrupt(params: {
    target: 'all' | 'agent' | 'planner'
    action: 'pause' | 'inject' | 'abort' | 'replan'
    targetAgent?: string
    targetTask?: string
    instruction?: string
  }) {
    if (!activeRun.value) return
    const interrupt: PendingInterrupt = {
      id: Date.now().toString(36),
      runId: activeRun.value.id,
      targetNodeId: params.targetTask || null,
      targetAgent: params.targetAgent || null,
      action: params.action,
      instruction: params.instruction || '',
      createdAt: new Date().toISOString(),
      status: 'pending',
    }
    state.pendingInterrupts.push(interrupt)
    state.status = 'pending'

    try {
      await api.interruptRun(activeRun.value.id, {
        target: params.target,
        action: params.action,
        target_agent: params.targetAgent,
        target_task: params.targetTask,
        instruction: params.instruction || '',
      })
      interrupt.status = 'sent'
      state.status = 'applied'
    } catch (e) {
      interrupt.status = 'rejected'
      state.status = 'idle'
      throw e
    }
  }

  /**
   * 暂停全部 Agent
   */
  async function pauseAll() {
    return sendInterrupt({ target: 'all', action: 'pause' })
  }

  /**
   * 暂停单个 Agent
   */
  async function pauseAgent(agentName: string) {
    return sendInterrupt({ target: 'agent', action: 'pause', targetAgent: agentName })
  }

  /**
   * 注入引导指令（Resume with Feedback）
   */
  async function injectGuidance(agentName: string | null, instruction: string) {
    const target = agentName ? 'agent' : 'all'
    return sendInterrupt({
      target,
      action: 'inject',
      targetAgent: agentName || undefined,
      instruction,
    })
  }

  /**
   * 终止整个运行
   */
  async function abortRun() {
    return sendInterrupt({ target: 'all', action: 'abort' })
  }

  /**
   * 恢复被中断的运行
   */
  async function resumeRun(decision: 'continue' | 'replan' | 'abort' = 'continue') {
    if (!activeRun.value) return
    const latest = state.pendingInterrupts.at(-1)
    if (!latest) return
    try {
      await api.resumeRun(activeRun.value.id, latest.id, decision)
      state.status = 'idle'
      state.guidanceMode = false
      state.guidanceTarget = null
    } catch (e) {
      throw e
    }
  }

  /**
   * 开启引导输入模式（暂停后）
   */
  function openGuidance(target: string | null = null) {
    state.guidanceMode = true
    state.guidanceTarget = target
  }

  function closeGuidance() {
    state.guidanceMode = false
    state.guidanceTarget = null
  }

  /**
   * 处理 SSE 中断事件更新
   */
  function handleInterruptEvent(event: RunEvent) {
    if (event.type === 'interrupt.received') {
      const commands = event.payload.commands as Array<Record<string, unknown>> | undefined
      if (commands) {
        for (const cmd of commands) {
          const existing = state.pendingInterrupts.find(
            (p) => p.id === (cmd.command_id as string),
          )
          if (existing) {
            existing.status = 'applied'
          }
        }
        state.status = 'applied'
      }
    }
    if (event.type === 'interrupt.resolved') {
      state.status = 'idle'
    }
  }

  function reset() {
    state.pendingInterrupts = []
    state.status = 'idle'
    state.guidanceMode = false
    state.guidanceTarget = null
  }

  return {
    interruptState: state,
    sendInterrupt,
    pauseAll,
    pauseAgent,
    injectGuidance,
    abortRun,
    resumeRun,
    openGuidance,
    closeGuidance,
    handleInterruptEvent,
    reset,
  }
}
