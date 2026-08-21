<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import DataTableWorkbench from '@/components/data-table/DataTableWorkbench.vue'
import type { DataTableConfig } from '@/components/data-table/types'
import PageShell from '@/components/PageShell.vue'
import { glossaryEntries, type GlossaryEntry, type GlossaryScope } from '@/glossary'

const { t } = useI18n()

function scopeLabel(scope: GlossaryScope): string {
  return t(scope === 'ai-agent-concept'
    ? 'terminology.scopes.aiAgentConcept'
    : 'terminology.scopes.projectTechnology')
}

const table: DataTableConfig<GlossaryEntry> = {
  id: 'terminology',
  ariaLabel: () => t('terminology.pagination.ariaLabel'),
  emptyMessage: () => t('terminology.empty'),
  loadErrorTitle: () => t('errors.requestFailed'),
  rowKey: (row) => row.key,
  provider: { mode: 'local', rows: () => glossaryEntries },
  search: {
    label: () => t('terminology.searchLabel'),
    placeholder: () => t('terminology.searchPlaceholder'),
    values: (row) => [
      row.english,
      row.zh,
      row.descriptionZh,
      row.descriptionEn,
      ...row.variants,
    ],
  },
  columns: [
    { key: 'term', label: () => t('terminology.termColumn'), value: (row) => row.english },
    { key: 'variants', label: () => t('terminology.variantsColumn'), value: (row) => row.variants.join(', ') },
    { key: 'category', label: () => t('terminology.categoryColumn'), value: (row) => scopeLabel(row.scope) },
    {
      key: 'explanations',
      label: () => t('terminology.explanationsAndSourcesColumn'),
      value: (row) => row.descriptionZh,
    },
  ],
  pageSize: 50,
  pageSizeOptions: [25, 50, 100],
}
</script>

<template>
  <PageShell>
    <DataTableWorkbench :config="table">
      <template #cell-term="{ row }">
        <strong :id="`term-${row.key}`" class="d-block text-break" lang="en">{{ row.english }}</strong>
        <span class="d-block text-break" lang="zh-CN">{{ row.zh }}</span>
        <span class="d-block font-monospace text-body-secondary text-break">{{ row.key }}</span>
      </template>
      <template #cell-variants="{ value }">
        <span class="font-monospace text-break">{{ value }}</span>
      </template>
      <template #cell-category="{ value }">
        <span class="text-break">{{ value }}</span>
      </template>
      <template #cell-explanations="{ row }">
        <p class="text-break mb-2" lang="zh-CN">{{ row.descriptionZh }}</p>
        <p class="text-body-secondary text-break mb-2" lang="en">{{ row.descriptionEn }}</p>
        <div class="d-flex flex-wrap gap-2">
          <a
            v-for="source in row.sources"
            :key="source.url"
            class="text-break"
            :href="source.url"
            target="_blank"
            rel="noopener noreferrer"
            :aria-label="t('terminology.openSource', { source: source.label })"
          >
            {{ source.label }}
          </a>
        </div>
      </template>
    </DataTableWorkbench>
  </PageShell>
</template>
