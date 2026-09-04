<script setup lang="ts">
import { LteAlert, LteButton } from '@adminlte/vue'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { managementApi, type ValidationIssue } from '@/api'
import ConfigDetail from '@/components/ConfigDetail.vue'
import ConfigurationLibraryActions from '@/components/ConfigurationLibraryActions.vue'
import ConfigurationLibraryFrame from '@/components/ConfigurationLibraryFrame.vue'
import CopyNameModal from '@/components/CopyNameModal.vue'
import DataTableWorkbench from '@/components/data-table/DataTableWorkbench.vue'
import type { DataTableConfig, DataTableRequest } from '@/components/data-table/types'
import ModalHost from '@/components/ModalHost.vue'
import PageShell from '@/components/PageShell.vue'
import type { SectionNavItem } from '@/components/sectionNav'
import ValidationChecklist from '@/components/ValidationChecklist.vue'
import { useConfirmation } from '@/composables/useConfirmation'
import { useConfigurationCatalog } from '@/composables/useConfigurationCatalog'
import { useConfigurationValidation } from '@/composables/useConfigurationValidation'
import { useManagementError } from '@/composables/useManagementError'
import { useToasts } from '@/composables/useToasts'
import { triggerBrowserDownload } from '@/utils/download'
import { matchesSearchText } from '@/utils/search'
import {
  agentLibraryCategories,
  bundleRoot,
  editLocation,
  routeCategory,
  type ConfigLibraryApi,
  type LibraryCategoryId,
  type LibraryDetailItem,
  type LibraryItem,
} from '@/pages/configLibrary'

const props = defineProps<{
  api?: ConfigLibraryApi
}>()

const { t } = useI18n()
const managementError = useManagementError()
const route = useRoute()
const router = useRouter()
const { notify } = useToasts()
const confirmation = useConfirmation()
const api = computed<ConfigLibraryApi>(() => props.api ?? managementApi)

const refreshing = ref(false)
const libraryTable = ref<{ reload: () => Promise<void> } | null>(null)
const detailItem = ref<LibraryDetailItem | null>(null)
const detailMode = ref<'card' | 'json'>('card')
const copyItem = ref<LibraryItem | null>(null)
const copyName = ref('')
const copyError = ref('')
const copying = ref(false)
const deletingUnsupportedBlockId = ref('')
let detailRequestSequence = 0
const {
  manifests,
  ready: catalogReady,
  error: catalogError,
  load: loadCatalog,
} = useConfigurationCatalog(
  () => api.value.getCatalog(),
  (error) => managementError.describe(error).display,
)
const {
  validation: repositoryValidation,
  validateNow: refreshRepositoryValidation,
} = useConfigurationValidation({
  buildRequest: () => ({}),
  validate: () => api.value.validateRepository(),
  immediate: false,
  errorMessage: (error) => managementError.describe(
    error,
    'errors.validationUnavailable',
  ).display,
})

const activeCategoryId = computed(() => (
  routeCategory(route.params.type)
))

const componentCategoryItems = computed<SectionNavItem[]>(() => (
  manifests.value.map((manifest) => ({
    id: manifest.type,
    label: t(`capabilities.${manifest.type}.label`),
  }))
))

const agentCategoryItems = computed<SectionNavItem[]>(() => (
  agentLibraryCategories.map((id) => ({
    id,
    label: t(`capabilities.${id}.label`),
  }))
))

const categoryItems = computed<SectionNavItem[]>(() => [
  ...componentCategoryItems.value,
  ...agentCategoryItems.value,
  { id: 'model-connection', label: t('capabilities.model-connection.label') },
  { id: 'mcp-connection', label: t('capabilities.mcp-connection.label') },
  { id: 'workflow', label: t('capabilities.workflow.label') },
])

const currentCategory = computed<LibraryCategoryId | null>(() => (
  categoryItems.value.some((item) => item.id === activeCategoryId.value)
    ? activeCategoryId.value as LibraryCategoryId
    : null
))

const currentCategoryLabel = computed(() => currentCategory.value
  ? t(`capabilities.${currentCategory.value}.label`)
  : t('library.unknownCategory', { type: activeCategoryId.value }))

const detailValue = computed<Record<string, unknown>>(() => (
  detailItem.value ? { ...detailItem.value } : {}
))

function isInstanceConnectionCategory(category: LibraryCategoryId | null): category is 'model-connection' | 'mcp-connection' {
  return category === 'model-connection' || category === 'mcp-connection'
}

async function refreshValidationIfOwned(): Promise<void> {
  await refreshRepositoryValidation()
}

async function listCategory(
  category: LibraryCategoryId,
  request: DataTableRequest,
): Promise<{ rows: LibraryItem[], total: number }> {
  const query = {
    q: request.query || undefined,
    offset: (request.page - 1) * request.pageSize,
    limit: request.pageSize,
  }
  if (category === 'main-agent') {
    const result = await api.value.listMainAgentSummaries(query)
    return { rows: result.items, total: result.total }
  }
  if (category === 'subagent-profile') {
    const result = await api.value.listSubagentSummaries(query)
    return { rows: result.items, total: result.total }
  }
  if (category === 'workflow') {
    const result = await api.value.listWorkflowSummaries(query)
    return { rows: result.items, total: result.total }
  }
  if (category === 'model-connection') {
    const items = (await api.value.listModelConnections()).filter((item) => (
      matchesSearchText(request.query, [item.name, item.id])
    ))
    return {
      rows: items.slice(query.offset, query.offset + request.pageSize),
      total: items.length,
    }
  }
  if (category === 'mcp-connection') {
    const items = (await api.value.listMcpConnections()).filter((item) => (
      matchesSearchText(request.query, [item.name, item.id, item.transport])
    ))
    return {
      rows: items.slice(query.offset, query.offset + request.pageSize),
      total: items.length,
    }
  }
  const result = await api.value.listBlockSummaries(category, query)
  return { rows: result.items, total: result.total }
}

async function getCategoryItem(
  category: LibraryCategoryId,
  id: string,
): Promise<LibraryDetailItem> {
  if (category === 'main-agent') return api.value.getMainAgent(id)
  if (category === 'subagent-profile') return api.value.getSubagent(id)
  if (category === 'workflow') {
    return api.value.getWorkflow(id)
  }
  if (category === 'model-connection') return api.value.getModelConnection(id)
  if (category === 'mcp-connection') return api.value.getMcpConnection(id)
  return api.value.getBlock(category, id)
}

async function downloadBundle(item: LibraryItem): Promise<void> {
  const category = currentCategory.value
  if (!category || isInstanceConnectionCategory(category)) return
  const download = await api.value.exportConfigurationBundle(bundleRoot(category, item.id))
  triggerBrowserDownload(download.blob, download.filename)
}

function libraryItemName(item: LibraryItem): string {
  return 'component_name' in item ? item.component_name : item.name
}

async function refresh(): Promise<void> {
  refreshing.value = true
  await Promise.all([libraryTable.value?.reload(), refreshValidationIfOwned()])
  refreshing.value = false
}

async function showDetail(item: LibraryItem): Promise<void> {
  const category = currentCategory.value
  if (!category) return
  const sequence = ++detailRequestSequence
  const detail = await getCategoryItem(category, item.id)
  if (sequence !== detailRequestSequence || category !== currentCategory.value) return
  detailMode.value = 'card'
  detailItem.value = detail
}

function closeDetail(): void {
  detailRequestSequence += 1
  detailItem.value = null
}

function editItem(item: LibraryItem): void {
  const category = currentCategory.value
  if (!category) return
  closeDetail()
  void router.push(editLocation(category, item.id))
}

function openCopy(item: LibraryItem): void {
  copyItem.value = item
  copyName.value = ''
  copyError.value = ''
}

function closeCopy(): void {
  if (copying.value) return
  copyItem.value = null
  copyName.value = ''
  copyError.value = ''
}

async function copyCurrentItem(): Promise<void> {
  const source = copyItem.value
  const category = currentCategory.value
  if (!source || !category) return
  if (!copyName.value.trim()) {
    copyError.value = t('library.copy.nameRequired')
    return
  }
  copying.value = true
  copyError.value = ''
  try {
    if (category === 'main-agent') {
      await api.value.copyMainAgent(source.id, copyName.value)
    } else if (category === 'subagent-profile') {
      await api.value.copySubagent(source.id, copyName.value)
    } else if (category === 'workflow') {
      await api.value.copyWorkflow(source.id, copyName.value)
    } else if (category === 'model-connection') {
      await api.value.copyModelConnection(source.id, copyName.value)
    } else if (category === 'mcp-connection') {
      await api.value.copyMcpConnection(source.id, copyName.value)
    } else {
      await api.value.copyBlock(category, source.id, copyName.value)
    }
    copying.value = false
    closeCopy()
    notify({ tone: 'success', title: t('library.copy.succeeded') })
    await Promise.all([libraryTable.value?.reload(), refreshValidationIfOwned()])
  } catch (error) {
    copyError.value = managementError.describe(error).display
  } finally {
    copying.value = false
  }
}

async function deleteUnsupportedBlock(issue: ValidationIssue): Promise<void> {
  if (
    issue.code !== 'storage.unknown_block_type'
    || !issue.owner_id
    || !issue.owner_type
  ) return
  const accepted = await confirmation.confirm({
    title: t('library.unsupportedBlock.title'),
    description: t('library.unsupportedBlock.description', {
      name: issue.owner_name,
      type: issue.owner_type,
    }),
    confirmLabel: t('common.delete'),
    cancelLabel: t('common.cancel'),
    dangerous: true,
  })
  if (!accepted) return
  deletingUnsupportedBlockId.value = issue.owner_id
  try {
    await api.value.deleteUnsupportedBlock(issue.owner_id)
    notify({ tone: 'success', title: t('library.unsupportedBlock.succeeded') })
    await refreshValidationIfOwned()
  } catch (error) {
    notify({
      tone: 'danger',
      title: t('library.unsupportedBlock.failed'),
      message: managementError.describe(error).display,
    })
  } finally {
    deletingUnsupportedBlockId.value = ''
  }
}

function deletedCount(result: unknown): number {
  if (!result || typeof result !== 'object' || !('deleted' in result)) return 0
  return Number((result as { deleted: unknown }).deleted) || 0
}

const libraryTableConfig: DataTableConfig<LibraryItem> = {
  id: 'configuration-library',
  ariaLabel: () => t('library.pagination.ariaLabel'),
  emptyMessage: () => t('library.empty'),
  filteredEmptyMessage: () => t('library.search.empty'),
  loadErrorTitle: () => t('library.loadFailed'),
  rowKey: (item) => item.id,
  provider: {
    mode: 'numbered',
    load: async (request) => {
      const category = currentCategory.value
      if (!category) throw new Error(t('library.unknownCategory', { type: activeCategoryId.value }))
      closeDetail()
      copyItem.value = null
      return listCategory(category, request)
    },
  },
  search: {
    label: () => t('library.search.label'),
    placeholder: () => t('library.search.placeholder'),
    values: (item) => [libraryItemName(item), item.id],
  },
  columns: [{ key: 'name', label: () => t('library.columns.name'), value: libraryItemName }],
  rowActions: [
    {
      key: 'view-configuration',
      label: () => t('common.view'),
      icon: 'view',
      tone: 'secondary',
      run: showDetail,
    },
    {
      key: 'edit-configuration',
      label: () => t('common.edit'),
      icon: 'edit',
      tone: 'secondary',
      run: editItem,
    },
    {
      key: 'copy-configuration',
      label: () => t('common.copy'),
      icon: 'copy',
      tone: 'secondary',
      run: openCopy,
    },
    {
      key: 'download-configuration',
      label: () => t('library.bundle.download'),
      icon: 'download',
      tone: 'secondary',
      run: downloadBundle,
      failureTitle: () => t('library.bundle.exportFailed'),
      visible: () => !isInstanceConnectionCategory(currentCategory.value),
    },
    {
      key: 'delete-configuration',
      label: () => t('common.delete'),
      icon: 'delete',
      busyLabel: () => t('common.deleting'),
      tone: 'danger',
      confirm: (item) => ({
        title: t('library.delete.title'),
        description: t('library.delete.description', { name: libraryItemName(item), id: item.id }),
        confirmLabel: t('common.delete'),
        cancelLabel: t('common.cancel'),
        dangerous: true,
      }),
      run: async (item) => {
        const category = currentCategory.value
        if (!category) return
        if (category === 'main-agent') await api.value.deleteMainAgent(item.id)
        else if (category === 'subagent-profile') await api.value.deleteSubagent(item.id)
        else if (category === 'workflow') await api.value.deleteWorkflow(item.id)
        else if (category === 'model-connection') await api.value.deleteModelConnection(item.id)
        else if (category === 'mcp-connection') await api.value.deleteMcpConnection(item.id)
        else await api.value.deleteBlock(category, item.id)
        if (detailItem.value?.id === item.id) closeDetail()
        await refreshValidationIfOwned()
      },
      successTitle: () => t('library.delete.succeeded'),
      failureTitle: () => t('library.delete.failed'),
      reloadAfter: 'current',
    },
  ],
  bulkAction: {
    label: () => t('library.deleteFiltered.action'),
    busyLabel: () => t('common.deleting'),
    icon: 'delete',
    enabled: (context) => !isInstanceConnectionCategory(currentCategory.value) && context.hasAppliedFilters && context.total > 0,
    confirm: (context) => ({
      title: t('library.deleteFiltered.title'),
      description: t('library.deleteFiltered.description', { count: context.total }),
      confirmLabel: t('common.delete'),
      cancelLabel: t('common.cancel'),
      dangerous: true,
    }),
    run: async (context) => {
      const category = currentCategory.value
      if (!category) return { deleted: 0 }
      if (isInstanceConnectionCategory(category)) return { deleted: 0 }
      const query = context.applied.query
      if (!query) return { deleted: 0 }
      const result = category === 'main-agent'
        ? await api.value.deleteMainAgentsMatching(query)
        : category === 'subagent-profile'
        ? await api.value.deleteSubagentsMatching(query)
        : category === 'workflow'
          ? await api.value.deleteWorkflowsMatching(query)
          : await api.value.deleteBlocksMatching(category, query)
      closeDetail()
      await refreshValidationIfOwned()
      return result
    },
    successTitle: (result) => t('library.deleteFiltered.succeeded', { count: deletedCount(result) }),
    failureTitle: () => t('library.deleteFiltered.failed'),
  },
  pageSize: 20,
  pageSizeOptions: [20, 50, 100],
}

onMounted(async () => {
  const validationRequest = refreshValidationIfOwned()
  await loadCatalog()
  await validationRequest
})
</script>

<template>
  <PageShell>
    <template #actions>
      <ConfigurationLibraryActions :api="api" :refreshing="refreshing" @imported="refresh" @refresh="refresh" />
    </template>

    <ConfigurationLibraryFrame
      :aside-test-id="'library-validation-region'"
      :content-test-id="'library-content-region'"
      :layout-test-id="'library-layout'"
      :manifests="manifests"
    >
      <LteAlert
        v-if="catalogError"
        class="mb-3"
        data-testid="catalog-error"
        :title="t('library.catalogUnavailable')"
        theme="danger"
      >
        {{ catalogError }}
      </LteAlert>

      <DataTableWorkbench
        v-if="catalogReady && currentCategory"
        :key="activeCategoryId"
        ref="libraryTable"
        :config="libraryTableConfig"
      >
        <template #cell-name="{ value }">
          <span class="fw-semibold text-break">{{ value }}</span>
        </template>
      </DataTableWorkbench>
      <LteAlert v-else-if="catalogReady" :title="currentCategoryLabel" theme="danger">
        {{ currentCategoryLabel }}
      </LteAlert>
      <template #aside>
        <ValidationChecklist
          :title="t('library.validationTitle')"
          :validation="repositoryValidation"
        >
          <template #issue-actions="{ issue }">
            <LteButton
              v-if="issue.code === 'storage.unknown_block_type' && issue.owner_id && issue.owner_type"
              class="action-button"
              :disabled="deletingUnsupportedBlockId === issue.owner_id"
              type="button"
              @click="deleteUnsupportedBlock(issue)"
            >
              <i class="bi bi-trash" aria-hidden="true" />
              {{ deletingUnsupportedBlockId === issue.owner_id
                ? t('common.deleting')
                : t('common.delete') }}
            </LteButton>
          </template>
        </ValidationChecklist>
      </template>
    </ConfigurationLibraryFrame>
  </PageShell>

  <ModalHost
    :open="detailItem !== null"
    size="wide"
    :title="detailItem ? t('library.detail.title', { name: libraryItemName(detailItem) }) : t('library.detail.titleFallback')"
    @close="closeDetail"
  >
    <div class="d-flex flex-wrap gap-2 mb-3">
      <div class="form-check">
        <input id="detail-card-mode" v-model="detailMode" class="form-check-input" type="radio" value="card">
        <label class="form-check-label" for="detail-card-mode">{{ t('library.detail.cardMode') }}</label>
      </div>
      <div class="form-check">
        <input
          id="detail-json-mode"
          v-model="detailMode"
          class="form-check-input"
          data-testid="detail-json-mode"
          type="radio"
          value="json"
        >
        <label class="form-check-label" for="detail-json-mode">{{ t('library.detail.jsonMode') }}</label>
      </div>
    </div>
    <ConfigDetail
      :hidden-keys="['id']"
      :mode="detailMode"
      :value="detailValue"
    />
    <template #footer>
      <LteButton class="action-button" type="button" @click="closeDetail">
        <i class="bi bi-x-lg" aria-hidden="true" />
        {{ t('common.close') }}
      </LteButton>
      <LteButton
        v-if="detailItem"
        class="action-button"
        type="button"
        @click="editItem(detailItem)"
      >
        <i class="bi bi-pencil" aria-hidden="true" />
        {{ t('common.edit') }}
      </LteButton>
    </template>
  </ModalHost>

  <CopyNameModal
    :busy="copying"
    :busy-label="t('common.copying')"
    error-test-id="copy-error"
    form-id="library-copy-form"
    :hint="t('library.copy.nameHint')"
    :name="copyName"
    :open="copyItem !== null"
    :submit-label="t('library.copy.submit')"
    :title="t('library.copy.title')"
    :description="copyItem ? t('library.copy.description', { name: libraryItemName(copyItem), id: copyItem.id }) : ''"
    :error="copyError"
    @close="closeCopy"
    @submit="copyCurrentItem"
    @update:name="copyName = $event"
  />
</template>
