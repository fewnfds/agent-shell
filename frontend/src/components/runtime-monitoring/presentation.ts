import type {
  LangGraphRunObservation,
  LangGraphRunStatus,
  LangGraphThreadObservation,
} from '@/api'

const ACTIVE_RUN_STATUSES = new Set<LangGraphRunStatus>(['pending', 'running'])

export function monitoringRunStatus(
  observation: LangGraphRunObservation,
): LangGraphRunStatus | 'unavailable' {
  return observation.run?.status ?? 'unavailable'
}

export function monitoringRunName(observation: LangGraphRunObservation): string {
  if (observation.relation?.resource_name) return observation.relation.resource_name
  const metadata = observation.run?.metadata
  const name = metadata?.graph_kind === 'agent'
    ? metadata.main_agent_name
    : metadata?.graph_kind === 'workflow'
      ? metadata.workflow_name
      : undefined
  return typeof name === 'string' && name ? name : observation.run_id
}

export function monitoringPrimaryRun(
  thread: LangGraphThreadObservation,
): LangGraphRunObservation | null {
  return [...thread.runs].reverse().find((run) => (
    ACTIVE_RUN_STATUSES.has(monitoringRunStatus(run) as LangGraphRunStatus)
  )) ?? thread.runs.at(-1) ?? null
}

export function monitoringThreadActive(thread: LangGraphThreadObservation): boolean {
  return thread.runs.some((run) => (
    ACTIVE_RUN_STATUSES.has(monitoringRunStatus(run) as LangGraphRunStatus)
  ))
}

export function monitoringThreadStatus(
  thread: LangGraphThreadObservation,
): LangGraphRunStatus | 'unavailable' {
  const active = thread.runs.find((run) => (
    ACTIVE_RUN_STATUSES.has(monitoringRunStatus(run) as LangGraphRunStatus)
  ))
  const primary = active ?? monitoringPrimaryRun(thread)
  return primary ? monitoringRunStatus(primary) : 'unavailable'
}

export function monitoringThreadGraphKind(
  thread: LangGraphThreadObservation,
): 'agent' | 'workflow' | null {
  const run = monitoringPrimaryRun(thread)
  if (run?.relation) return run.relation.graph_kind
  const kind = run?.run?.metadata.graph_kind
  return kind === 'agent' || kind === 'workflow' ? kind : null
}

export function monitoringStatusIcon(status: string): string {
  return ({
    pending: 'bi-hourglass-split',
    running: 'bi-arrow-repeat',
    success: 'bi-check2-circle',
    error: 'bi-exclamation-triangle',
    timeout: 'bi-clock-history',
    interrupted: 'bi-pause-circle',
    unavailable: 'bi-dash-circle',
  } as Record<string, string>)[status] ?? 'bi-circle'
}

export function monitoringLocalTime(value: string): string {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

export function monitoringCompactTime(value: string): string {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat(undefined, {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hourCycle: 'h23',
      }).format(parsed)
}

export function monitoringShortId(value: string): string {
  return value.length > 12 ? `…${value.slice(-8)}` : value
}
