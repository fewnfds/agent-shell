import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'

import TerminologyPage from './TerminologyPage.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'en',
  messages: {
    en: {
      terminology: {
        eyebrow: 'Glossary',
        title: 'Terminology',
        description: 'Bilingual terminology',
        searchLabel: 'Search terminology',
        searchPlaceholder: 'Search',
        resultCount: '{count} of {total}',
        applied: 'Applied: {filters}',
        appliedQuery: 'search {query}',
        appliedCategories: 'categories {categories}',
        pagination: { ariaLabel: 'Terminology pages' },
        empty: 'No matching terms',
        termColumn: 'Term',
        variantsColumn: 'Variants',
        categoryColumn: 'Category',
        explanationsAndSourcesColumn: 'Explanations and sources',
        openSource: 'Open {source}',
        scopes: {
          aiAgentConcept: 'AI and Agent concept',
          projectTechnology: 'Project technology',
        },
      },
      common: {
        all: 'All',
        search: 'Search',
        reset: 'Reset',
        itemSeparator: '; ',
        previousPage: 'Previous page',
        nextPage: 'Next page',
        pagination: {
          first: 'First',
          last: 'Last',
          pageLabel: 'Page {page}',
          pageSize: 'Page size',
          pageSizeOption: '{count} items',
          jump: 'Go to page',
          jumpAction: 'Go',
          numberedSummary: '{total} items, {start}-{end}, page {page} of {totalPages}',
        },
      },
    },
  },
})

describe('TerminologyPage', () => {
  it('filters a single-header scroll list and keeps external sources safe', async () => {
    const wrapper = mount(TerminologyPage, {
      global: {
        plugins: [i18n],
      },
    })
    expect(wrapper.findAll('[data-testid="data-table-row"]')).toHaveLength(50)
    expect(wrapper.findAll('[data-testid="term-card"]')).toHaveLength(0)
    expect(wrapper.get('[data-testid="data-table"]').find('table').exists()).toBe(true)
    expect(wrapper.findAll('thead')).toHaveLength(1)
    expect(wrapper.findAll('th').map((item) => item.text())).toEqual([
      'Term',
      'Variants',
      'Category',
      'Explanations and sources',
    ])
    expect(wrapper.find('tbody .badge').exists()).toBe(false)
    expect(wrapper.find('tbody button').exists()).toBe(false)

    await wrapper.get('input[type="search"]').setValue('goal-directed computational system')
    await wrapper.get('form[role="search"]').trigger('submit')
    expect(wrapper.findAll('[data-testid="data-table-row"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Agent')

    const source = wrapper.get('a')
    expect(source.attributes('target')).toBe('_blank')
    expect(source.attributes('rel')).toBe('noopener noreferrer')

    await wrapper.get('input[type="search"]').setValue('no-such-glossary-entry')
    await wrapper.get('form[role="search"]').trigger('submit')
    expect(wrapper.findAll('[data-testid="data-table-row"]')).toHaveLength(0)
    expect(wrapper.text()).toContain('No matching terms')
  })
})
