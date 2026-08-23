import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useConfirmation } from '@/composables/useConfirmation'
import { useToasts } from '@/composables/useToasts'
import { en } from '@/locales/en'

import DataTableWorkbench from './DataTableWorkbench.vue'
import type { DataTableConfig } from './types'

interface Row {
  id: string
  name: string
  scope: string
}

const rows: Row[] = [
  { id: '1', name: 'Alpha', scope: 'one' },
  { id: '2', name: 'Beta', scope: 'two' },
  { id: '3', name: 'Gamma 中文', scope: 'one' },
]

function i18n() {
  return createI18n({ legacy: false, locale: 'en', messages: { en } })
}

function baseConfig(): Omit<DataTableConfig<Row>, 'provider'> {
  return {
    id: 'records',
    ariaLabel: 'Record pages',
    emptyMessage: 'No records',
    loadErrorTitle: 'Load failed',
    rowKey: (row) => row.id,
    columns: [{ key: 'name', label: 'Name', value: (row) => row.name }],
    search: { label: 'Search', placeholder: 'Name', values: (row) => [row.name] },
    filters: [{
      key: 'scope',
      kind: 'multi',
      label: 'Scope',
      options: [{ value: 'one', label: 'One' }, { value: 'two', label: 'Two' }],
      values: (row) => row.scope,
    }],
    pageSize: 2,
    pageSizeOptions: [2, 3],
  }
}

afterEach(() => {
  useConfirmation().cancel()
  const toasts = useToasts()
  for (const toast of toasts.items.value) toasts.dismiss(toast.id)
})

describe('DataTableWorkbench', () => {
  it('owns local search, enum filtering, paging, and reset', async () => {
    const remove = vi.fn().mockResolvedValue({ deleted: 3 })
    const config: DataTableConfig<Row> = {
      ...baseConfig(),
      provider: { mode: 'local', rows: () => rows },
      bulkAction: {
        label: 'Delete',
        enabled: () => true,
        icon: 'delete',
        confirm: () => ({
          title: 'Delete?',
          description: 'Delete matching rows',
          confirmLabel: 'Delete',
          cancelLabel: 'Cancel',
          dangerous: true,
        }),
        run: remove,
        failureTitle: 'Delete failed',
      },
    }
    const wrapper = mount(DataTableWorkbench, {
      props: { config },
      global: { plugins: [i18n()] },
    })

    expect(wrapper.findAll('.card')).toHaveLength(2)
    expect(wrapper.findAll('.card-header')).toHaveLength(0)
    expect(wrapper.get('thead').classes()).toContain('management-table-head')
    expect(wrapper.text()).toContain('3 items, 1–2, page 1 of 2')
    expect(wrapper.findAll('[data-testid="data-table-row"]')).toHaveLength(2)
    const filterActions = wrapper.findAll('form[role="search"] button')
    expect(filterActions).toHaveLength(3)
    expect(filterActions.every((button) => button.classes().includes('action-button'))).toBe(true)
    const peerLegends = wrapper.findAll('.collection-filter-legend')
    expect(peerLegends.length).toBeGreaterThan(0)
    expect(peerLegends.every((legend) => legend.classes().includes('form-label'))).toBe(true)
    await wrapper.get('#records-query').setValue('ＧＡＭＭＡ 中文')
    await wrapper.get('#records-filter-scope-one').setValue(true)
    await wrapper.get('form[role="search"]').trigger('submit')
    expect(wrapper.findAll('[data-testid="data-table-row"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Gamma 中文')

    await wrapper.findAll('button').find((button) => button.text() === 'Reset')!.trigger('click')
    expect(wrapper.findAll('[data-testid="data-table-row"]')).toHaveLength(2)

    await wrapper.findAll('button').find((button) => button.text() === 'Delete')!.trigger('click')
    useConfirmation().accept()
    await flushPromises()
    expect(remove).toHaveBeenCalledWith(expect.objectContaining({
      matchingRows: rows,
      visibleRows: rows.slice(0, 2),
    }))
  })

  it('uses an opt-in clickable row for details without hijacking row actions', async () => {
    const inspect = vi.fn()
    const config: DataTableConfig<Row> = {
      ...baseConfig(),
      provider: { mode: 'local', rows: () => rows },
      detail: true,
      rowActions: [{
        key: 'inspect',
        label: 'Inspect',
        icon: 'view',
        tone: 'primary',
        run: inspect,
      }],
    }
    const wrapper = mount(DataTableWorkbench, {
      props: { config },
      slots: { detail: '<p data-testid="row-detail">Detail</p>' },
      global: { plugins: [i18n()] },
    })
    const row = wrapper.findAll('[data-testid="data-table-row"]')[0]

    expect(row.attributes('tabindex')).toBe('0')
    expect(row.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('[data-testid="data-table-detail"]').exists()).toBe(false)
    expect(wrapper.findAll('button').some(button => button.text() === 'Expand')).toBe(false)

    await row.trigger('click')
    expect(row.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('[data-testid="data-table-detail"]').exists()).toBe(true)

    await wrapper.findAll('[data-action="inspect"]')[0].trigger('click')
    expect(inspect).toHaveBeenCalledWith(rows[0])
    expect(wrapper.find('[data-testid="data-table-detail"]').exists()).toBe(true)

    await row.trigger('keydown', { key: ' ' })
    expect(wrapper.find('[data-testid="data-table-detail"]').exists()).toBe(false)
  })

  it('owns numbered requests and discards an older response', async () => {
    let resolveFirst!: (value: { rows: Row[]; total: number }) => void
    const load = vi.fn()
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockResolvedValueOnce({ rows: [{ id: 'new', name: 'New', scope: 'one' }], total: 1 })
    const config: DataTableConfig<Row> = {
      ...baseConfig(),
      provider: { mode: 'numbered', load },
    }
    const wrapper = mount(DataTableWorkbench, {
      props: { config },
      global: { plugins: [i18n()] },
    })

    await wrapper.get('#records-query').setValue('new')
    await wrapper.get('form[role="search"]').trigger('submit')
    await flushPromises()
    resolveFirst({ rows: [{ id: 'old', name: 'Old', scope: 'one' }], total: 1 })
    await flushPromises()

    expect(load).toHaveBeenLastCalledWith(expect.objectContaining({
      query: 'new',
      page: 1,
      pageSize: 2,
    }))
    expect(wrapper.text()).toContain('New')
    expect(wrapper.text()).not.toContain('Old')
  })

  it('reloads the last valid numbered page when the remote total shrinks', async () => {
    let total = 5
    const load = vi.fn(async ({ page }: { page: number }) => ({
      rows: page === 1
        ? rows.slice(0, 2)
        : page === 3 && total === 5 ? rows.slice(2) : [],
      total,
    }))
    const config: DataTableConfig<Row> = {
      ...baseConfig(),
      provider: { mode: 'numbered', load },
    }
    const wrapper = mount(DataTableWorkbench, {
      props: { config },
      global: { plugins: [i18n()] },
    })
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text() === '3')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('page 3 of 3')

    total = 2
    await (wrapper.vm as unknown as { reload: () => Promise<void> }).reload()
    await flushPromises()

    expect(load.mock.calls.map(([request]) => request.page)).toEqual([1, 3, 3, 1])
    expect(wrapper.text()).toContain('2 items, 1–2, page 1 of 1')
    expect(wrapper.text()).toContain('Alpha')
  })

  it('owns datetime validation and merges narrow external filter updates', async () => {
    const load = vi.fn().mockResolvedValue({ rows: [rows[0]], total: 1 })
    const config: DataTableConfig<Row> = {
      ...baseConfig(),
      provider: { mode: 'numbered', load },
      filters: [
        ...(baseConfig().filters ?? []),
        {
          key: 'started_at',
          kind: 'datetime',
          label: 'From',
          initialValue: '2026-08-01T00:00:00',
        },
        {
          key: 'ended_at',
          kind: 'datetime',
          label: 'To',
          initialValue: '2026-08-01T12:00:00',
        },
      ],
      validateQuery: ({ filters }) => String(filters.ended_at) < String(filters.started_at)
        ? 'Invalid time window'
        : null,
    }
    const wrapper = mount(DataTableWorkbench, {
      props: { config },
      global: { plugins: [i18n()] },
    })
    await flushPromises()

    await wrapper.get('#records-filter-ended_at').setValue('2026-07-31T23:59:59')
    await wrapper.get('form[role="search"]').trigger('submit')
    await flushPromises()
    expect(load).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('Invalid time window')

    await wrapper.get('#records-filter-ended_at').setValue('2026-08-01T13:00:00')
    await wrapper.get('#records-filter-scope-one').setValue(true)
    await wrapper.get('form[role="search"]').trigger('submit')
    await flushPromises()
    expect(load).toHaveBeenLastCalledWith(expect.objectContaining({
      filters: expect.objectContaining({
        scope: ['one'],
        started_at: '2026-08-01T00:00:00',
        ended_at: '2026-08-01T13:00',
      }),
    }))

    await (wrapper.vm as unknown as {
      setQuery: (value: { filters: Record<string, string> }) => Promise<boolean>
    }).setQuery({ filters: { ended_at: '2026-08-01T14:00:00' } })
    expect(load).toHaveBeenLastCalledWith(expect.objectContaining({
      filters: expect.objectContaining({
        scope: ['one'],
        started_at: '2026-08-01T00:00:00',
        ended_at: '2026-08-01T14:00:00',
      }),
    }))
  })
})
