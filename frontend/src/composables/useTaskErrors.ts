import { computed, ComputedRef } from 'vue'
import type { RunEvent, TaskError } from '../types'

/**
 * 从 agent.failed 和 run.failed 事件中提取并分类错误。
 */
export function useTaskErrors(events: ComputedRef<RunEvent[]>) {
  /**
   * 错误分类（复用 EventTimeline 的 failureCategory 逻辑）
   */
  function classifyErrorType(errorText: string): TaskError['type'] {
    const lower = errorText.toLowerCase()
    if (lower.includes('timeout') || lower.includes('超时') || lower.match(/超过\d+秒/)) return 'TIMEOUT'
    if (lower.includes('cancel') || lower.includes('取消') || lower.includes('abort')) return 'USER_CANCEL'
    if (
      lower.includes('max_turn') ||
      lower.includes('最大交互轮次')
    )
      return 'TIMEOUT'
    if (lower.includes('permission') || lower.includes('权限') || lower.includes('forbidden')) return 'EXCEPTION'
    if (lower.includes('auth') || lower.includes('鉴权') || lower.includes('401') || lower.includes('403')) return 'EXCEPTION'
    if (lower.includes('error') || lower.includes('fail') || lower.includes('exception') || lower.includes('失败') || lower.includes('错误'))
      return 'EXCEPTION'
    return 'UNKNOWN'
  }

  /**
   * 所有分类错误列表
   */
  const errors = computed<TaskError[]>(() => {
    const result: TaskError[] = []

    for (const e of events.value) {
      if (e.type === 'agent.failed') {
        const errorMsg =
          (e.payload.error as string) ||
          (e.payload.summary as string) ||
          'Agent 执行错误'
        result.push({
          nodeId: `task-${e.task_id || 'unknown'}`,
          type: classifyErrorType(errorMsg),
          message: errorMsg,
          stack: null, // 待后端补充
        })
      }
      if (e.type === 'run.failed') {
        const errorMsg = (e.payload.error as string) || (e.payload.text as string) || '运行失败'
        result.push({
          nodeId: `orchestrator-${e.run_id}`,
          type: classifyErrorType(errorMsg),
          message: errorMsg,
          stack: null,
        })
      }
    }

    return result
  })

  /**
   * 有错误的节点 ID 集合
   */
  const errorNodeIds = computed<Set<string>>(
    () => new Set(errors.value.map((e) => e.nodeId)),
  )

  /**
   * 错误计数
   */
  const errorCount = computed(() => errors.value.length)

  /**
   * 按 nodeId 获取错误
   */
  function errorsForNode(nodeId: string): TaskError[] {
    return errors.value.filter((e) => e.nodeId === nodeId)
  }

  return {
    errors,
    errorNodeIds,
    errorCount,
    errorsForNode,
    classifyErrorType,
  }
}
