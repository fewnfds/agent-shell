import type { ResponseStreamPolicy } from '@/api'

export function defaultResponseStreamPolicy(): ResponseStreamPolicy {
  return {
    queue: { mode: 'fair_turns', successor_grace_seconds: 2 },
    assistant_text: {
      delivery: 'live',
      live_wrapper: { start: '', end: '' },
    },
    reasoning: {
      delivery: 'live',
      live_wrapper: {
        start: '<details type="agent"><summary>Reasoning</summary>',
        end: '</details>\n',
      },
    },
    subagent_content: { delivery: 'hidden' },
    tools: { delivery: 'paired' },
    subagent_lifecycle: { delivery: 'activity' },
    workflow_custom: { delivery: 'complete' },
    workflow_lifecycle: { delivery: 'activity' },
    activity: {
      announce_start: true,
      announce_queued: true,
      hidden_delta_pulse_seconds: 15,
      quiet_notice_after_seconds: 30,
      quiet_notice_repeat_seconds: 60,
    },
    source_overrides: [],
  }
}

export function cloneResponseStreamPolicy(
  policy: ResponseStreamPolicy,
): ResponseStreamPolicy {
  return JSON.parse(JSON.stringify(policy)) as ResponseStreamPolicy
}
