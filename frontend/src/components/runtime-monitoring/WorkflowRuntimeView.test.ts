import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'

import { en } from '@/locales/en'

import WorkflowRuntimeView from './WorkflowRuntimeView.vue'

const VueFlowStub = defineComponent({
  name: 'VueFlow',
  props: [
    'nodes',
    'edges',
    'nodesDraggable',
    'nodesConnectable',
    'edgesUpdatable',
    'elementsSelectable',
    'deleteKeyCode',
  ],
  template: '<div data-testid="workflow-flow" />',
})

describe('WorkflowRuntimeView', () => {
  it('keeps the canvas read-only and highlights every node in latest State next', () => {
    const wrapper = mount(WorkflowRuntimeView, {
      props: {
        graph: {
          nodes: [
            { id: '__start__' },
            { id: 'research', data: { name: 'Research' } },
            { id: 'review', data: { name: 'Review' } },
            { id: '__end__' },
          ],
          edges: [
            { source: '__start__', target: 'research' },
            { source: '__start__', target: 'review' },
            { source: 'research', target: '__end__' },
            { source: 'review', target: '__end__' },
          ],
        },
        state: { values: { answer: 42 }, next: ['research', 'review'] },
        loading: false,
      },
      global: {
        plugins: [createI18n({ legacy: false, locale: 'en', messages: { en } })],
        stubs: { VueFlow: VueFlowStub },
      },
    })

    const flow = wrapper.getComponent(VueFlowStub)
    const nodes = flow.props('nodes') as Array<{
      id: string
      data: { active: boolean }
      selectable: boolean
    }>
    const edges = flow.props('edges') as Array<{ animated: boolean }>
    expect(nodes.filter((node) => node.data.active).map((node) => node.id))
      .toEqual(['research', 'review'])
    expect(nodes.every((node) => node.selectable === false)).toBe(true)
    expect(edges.every((edge) => edge.animated === false)).toBe(true)
    expect(flow.props('nodesDraggable')).toBe(false)
    expect(flow.props('nodesConnectable')).toBe(false)
    expect(flow.props('edgesUpdatable')).toBe(false)
    expect(flow.props('elementsSelectable')).toBe(false)
    expect(flow.props('deleteKeyCode')).toBeNull()
  })
})
