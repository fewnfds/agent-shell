import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'

import PageShell from './PageShell.vue'

const messages = {
  navigation: {
    system: 'System',
    agents: 'Agents',
    sectionAriaLabel: 'Current section pages',
    sections: {
      systemSettings: 'System settings',
      messageInterception: 'Message interception',
      eventFeed: 'Log center',
      workflowLifecycles: 'Runtime monitoring',
      mainAgent: 'Main Agent',
      subagents: 'Subagent',
    },
  },
}

function i18n() {
  return createI18n({
    legacy: false,
    locale: 'en',
    messages: { en: messages },
  })
}

describe('PageShell', () => {
  it('shows every child page as buttons for the active route group', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }],
    })
    await router.push('/system/events')
    await router.isReady()

    const wrapper = mount(PageShell, {
      slots: { default: '<p>Content</p>' },
      global: { plugins: [router, i18n()] },
    })

    expect(wrapper.find('.app-content-header').exists()).toBe(false)
    expect(wrapper.get('.app-content > .container-fluid').classes()).toContain('pt-3')
    const buttons = wrapper.get('[data-testid="section-nav"]').findAll('button')
    expect(buttons.map((button) => button.text())).toEqual([
      'System settings',
      'Message interception',
      'Log center',
      'Runtime monitoring',
    ])
    expect(buttons[2]?.attributes('aria-current')).toBe('page')
    expect(buttons[2]?.classes()).toContain('btn-primary')

    await buttons[1]?.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/system/message-interception')
  })

  it('starts with content and omits child navigation outside a route group', () => {
    const wrapper = mount(PageShell, {
      slots: { default: '<p>Content</p>' },
      global: { plugins: [i18n()] },
    })

    expect(wrapper.find('.app-content-header').exists()).toBe(false)
    expect(wrapper.get('.app-content').text()).toContain('Content')
    expect(wrapper.find('[data-testid="section-nav"]').exists()).toBe(false)
  })

  it('keeps the parent section active on a nested detail route', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }],
    })
    await router.push('/system/workflow-lifecycles/lifecycle-1/monitoring')
    await router.isReady()

    const wrapper = mount(PageShell, {
      slots: { default: '<p>Content</p>' },
      global: { plugins: [router, i18n()] },
    })

    const active = wrapper.get('[data-testid="section-nav"] [aria-current="page"]')
    expect(active.text()).toBe('Runtime monitoring')
  })
})
