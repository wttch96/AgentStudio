import { ref, watch, onBeforeUnmount, type Ref } from 'vue'
import type { Run, TimeoutState } from '../types'

export interface TimeoutDetectionConfig {
  /** Agent 执行超时阈值 (ms)，默认从 scheduler 读取，回退到此值 */
  defaultTimeoutMs: number
  /** 检查间隔 (ms) */
  checkIntervalMs: number
}

/**
 * 客户端超时检测。
 * 监控活跃运行中 Agent 节点的执行时间，
 * 超过阈值时标记为 TIMEOUT。
 */
export function useTimeoutDetection(
  activeRun: Ref<Run | null>,
  config?: Partial<TimeoutDetectionConfig>,
) {
  const {
    defaultTimeoutMs = 300_000,  // 5 分钟
    checkIntervalMs = 2_000,      // 2 秒轮询
  } = config ?? {}

  const timeoutIds = ref<Set<string>>(new Set())
  const timeoutStates = ref<TimeoutState[]>([])
  let timer: ReturnType<typeof setInterval> | undefined

  function check() {
    const run = activeRun.value
    if (!run || !['running', 'queued'].includes(run.status)) {
      stop()
      return
    }

    const now = Date.now()
    const threshold = defaultTimeoutMs

    // 检查运行级超时
    if (run.started_at) {
      const runElapsed = now - new Date(run.started_at).getTime()
      if (runElapsed > threshold * 3) {
        // 运行级超时 — 3 倍 agent 超时
        const existing = timeoutStates.value.find(
          (t) => t.nodeId === 'run-level',
        )
        if (!existing) {
          timeoutStates.value.push({
            nodeId: 'run-level',
            startedAt: run.started_at,
            thresholdMs: threshold * 3,
            elapsedMs: runElapsed,
            isTimedOut: true,
          })
        } else {
          existing.elapsedMs = runElapsed
          existing.isTimedOut = true
        }
      }
    }
  }

  function start() {
    stop()
    timer = setInterval(check, checkIntervalMs)
  }

  function stop() {
    if (timer !== undefined) {
      clearInterval(timer)
      timer = undefined
    }
  }

  function reset() {
    timeoutIds.value = new Set()
    timeoutStates.value = []
    stop()
  }

  /**
   * 将超时节点添加到集合（由 useNodeGraph 调用）
   */
  function markTimedOut(nodeId: string, startedAt: string) {
    const set = new Set(timeoutIds.value)
    set.add(nodeId)
    timeoutIds.value = set
    timeoutStates.value.push({
      nodeId,
      startedAt,
      thresholdMs: defaultTimeoutMs,
      elapsedMs: Date.now() - new Date(startedAt).getTime(),
      isTimedOut: true,
    })
  }

  // 监听活跃运行状态变化
  watch(
    () => activeRun.value?.status,
    (status) => {
      if (status === 'queued' || status === 'running') {
        start()
      } else {
        stop()
      }
    },
    { immediate: true },
  )

  onBeforeUnmount(stop)

  return {
    timeoutIds,
    timeoutStates,
    markTimedOut,
    reset,
    start,
    stop,
  }
}
