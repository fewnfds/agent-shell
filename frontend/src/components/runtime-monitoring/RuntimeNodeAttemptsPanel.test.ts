import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'

import type {
  RuntimeMonitoringNodeAttemptPage,
  RuntimeMonitoringNodeSummary,
} from '@/api'
import PaginationControls from '@/components/PaginationControls.vue'
import { en } from '@/locales/en'

import RuntimeNodeAttemptsPanel from './RuntimeNodeAttemptsPanel.vue'

const summary: RuntimeMonitoringNodeSummary = {
  workflow_node_id: 'agent-1',
  first_sequence: 1,
  latest_sequence: 42,
  first_started_at: '2026-09-03T00:00:00Z',
  latest_started_at: '2026-09-03T00:00:02Z',
  attempt_count: 2,
  status_counts: { completed: 1, failed: 1 },
}

function attemptPage(
  overrides: Partial<RuntimeMonitoringNodeAttemptPage> = {},
): RuntimeMonitoringNodeAttemptPage {
  return {
    availability: 'available',
    read_at: '2026-09-03T00:00:10Z',
    items: [{
      sequence: 42,
      lifecycle_id: 'lifecycle-1',
      run_id: 'run-1',
      workflow_node_id: 'agent-1',
      invocation_id: 'invocation-7',
      attempt: 2,
      node_first_attempt_time: 1788393600,
      started_at: '2026-09-03T00:00:02Z',
      finished_at: '2026-09-03T00:00:04Z',
      status: 'failed',
      error_code: 'provider_unavailable',
    }],
    page: 1,
    page_size: 20,
    total: 1,
    total_pages: 1,
    ...overrides,
  }
}

function mountPanel(page: RuntimeMonitoringNodeAttemptPage | null = attemptPage()) {
  return mount(RuntimeNodeAttemptsPanel, {
    props: {
      nodeId: 'agent-1',
      nodeType: 'agent',
      summary,
      page,
      loading: false,
      error: '',
    },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'en', messages: { en } })],
    },
  })
}

describe('RuntimeNodeAttemptsPanel', () => {
  it('renders the persisted Node attempt fields without deriving extra runtime meaning', () => {
    const wrapper = mountPanel()

    expect(wrapper.text()).toContain('agent-1')
    expect(wrapper.text()).toContain('2 recorded attempts')
    expect(wrapper.text()).toContain('Attempt 2')
    expect(wrapper.text()).toContain('invocation-7')
    expect(wrapper.text()).toContain('42')
    expect(wrapper.text()).toContain('failed')
    expect(wrapper.text()).toContain('provider_unavailable')
  })

  it('shows resource availability and an empty result independently', () => {
    const wrapper = mountPanel(attemptPage({
      availability: 'unavailable',
      items: [],
      total: 0,
    }))

    expect(wrapper.text()).toContain('Node attempt data is unavailable.')
    expect(wrapper.text()).toContain('No Node attempts were returned.')
  })

  it('forwards page and page-size changes to the page controller', () => {
    const wrapper = mountPanel(attemptPage({
      page: 1,
      page_size: 20,
      total: 25,
      total_pages: 2,
    }))
    const pagination = wrapper.getComponent(PaginationControls)

    pagination.vm.$emit('change', 2)
    pagination.vm.$emit('pageSizeChange', 50)

    expect(wrapper.emitted('pageChange')).toEqual([[2]])
    expect(wrapper.emitted('pageSizeChange')).toEqual([[50]])
  })
})
