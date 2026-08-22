<script setup lang="ts">
import { LteAlert, LteButton } from '@adminlte/vue'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { managementApi, type ConfigurationBundlePreview, type ValidationIssue } from '@/api'
import ConfigDetail from '@/components/ConfigDetail.vue'
import ConfigurationLibraryFrame from '@/components/ConfigurationLibraryFrame.vue'
import CopyNameModal from '@/components/CopyNameModal.vue'
import DataTableWorkbench from '@/components/data-table/DataTableWorkbench.vue'
import type { DataTableConfig } from '@/components/data-table/types'
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
import {
  agentLibraryCategories,
  bundleRoot,
  editLocation,
  routeCategory,
  type ConfigLibraryApi,
  type LibraryCategoryId,
  type LibraryItem,
} from '@/pages/configLibrary'

const props = defineProps<{
  api?: ConfigLibraryApi
}>()

const { t, te } = useI18n()
const managementError = useManagementError()
const route = useRoute()
const router = useRouter()
const { notify } = useToasts()
const confirmation = useConfirmation()
const api = computed<ConfigLibraryApi>(() => props.api ?? managementApi)

const refreshing = ref(false)
const libraryTable = ref<{ reload: () => Promise<void> } | null>(null)
const detailItem = ref<LibraryItem | null>(null)
const detailMode = ref<'card' | 'json'>('card')
const copyItem = ref<LibraryItem | null>(null)
const copyName = ref('')
const copyError = ref('')
const copying = ref(false)
const deletingUnsupportedBlockId = ref('')
const bundleInput = ref<HTMLInputElement | null>(null)
const bundleFile = ref<File | null>(null)
const bundlePreview = ref<ConfigurationBundlePreview | null>(null)
const bundleNames = ref<Record<string, string>>({})
const bundleBindings = ref<Record<string, { value: string; path_origin?: 'absolute' | 'data-root-relative' }>>({})
const bundleBusy = ref(false)
const bundleError = ref('')
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
  { id: 'parent-workflow', label: t('capabilities.parent-workflow.label') },
  { id: 'child-workflow', label: t('capabilities.child-workflow.label') },
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

function bindingIsComplete(binding: ConfigurationBundlePreview['filesystem_bindings'][number]): boolean {
  const resolution = bundleBindings.value[binding.binding_id]
  if (!resolution?.value.trim()) return false
  return binding.kind !== 'mapped-directory' || Boolean(resolution.path_origin)
}

const bundleBlockingErrors = computed(() => {
  const preview = bundlePreview.value
  if (!preview) return []
  return preview.errors.filter((issue) => {
    if (issue.code !== 'filesystem_binding_required') return true
    const binding = preview.filesystem_bindings.find((candidate) => (
      candidate.source_id === issue.source_id && candidate.path === issue.path
    ))
    return !binding || !bindingIsComplete(binding)
  })
})

const canImport = computed(() => {
  const preview = bundlePreview.value
  if (!preview || bundleBlockingErrors.value.length > 0) return false
  if (preview.records.some((record) => !bundleNames.value[record.source_id]?.trim())) {
    return false
  }
  return preview.filesystem_bindings.every(bindingIsComplete)
})

async function refreshValidationIfOwned(): Promise<void> {
  await refreshRepositoryValidation()
}

function bundleIssueText(issue: ConfigurationBundlePreview['errors'][number]): string {
  if (issue.message_key && te(issue.message_key)) {
    return t(issue.message_key, issue.message_args ?? {})
  }
  return t('library.bundle.unknownIssue', { code: issue.code })
}

async function listCategory(category: LibraryCategoryId): Promise<LibraryItem[]> {
  if (category === 'main-agent') return api.value.listMainAgents()
  if (category === 'subagent-profile') return api.value.listSubagents()
  if (category === 'parent-workflow') return api.value.listWorkflows('parent')
  if (category === 'child-workflow') return api.value.listWorkflows('child')
  if (category === 'model-connection') return api.value.listModelConnections()
  return api.value.listBlocks(category)
}

async function downloadBundle(item: LibraryItem): Promise<void> {
  const category = currentCategory.value
  if (!category || category === 'model-connection') return
  const download = await api.value.exportConfigurationBundle(bundleRoot(category, item.id))
  triggerBrowserDownload(download.blob, download.filename)
}

function openBundlePicker(): void { bundleInput.value?.click() }
async function selectBundle(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0]
  ;(event.target as HTMLInputElement).value = ''
  if (!file) return
  bundleBusy.value = true
  bundleError.value = ''
  try {
    const preview = await api.value.previewConfigurationBundle(file)
    bundleFile.value = file
    bundlePreview.value = preview
    bundleNames.value = Object.fromEntries(preview.records.map((record) => [
      record.source_id,
      record.requires_confirmation ? '' : record.selected_name,
    ]))
    bundleBindings.value = Object.fromEntries(preview.filesystem_bindings.map((binding) => [binding.binding_id, {
      value: binding.target_value ?? '',
      ...(binding.source_path_origin === 'data-root-relative' ? { path_origin: 'data-root-relative' as const } : {}),
    }]))
  } catch (cause) {
    bundleError.value = managementError.describe(cause).display
    bundleFile.value = null
    bundlePreview.value = null
  } finally {
    bundleBusy.value = false
  }
}
function closeBundle(): void {
  if (bundleBusy.value) return
  bundleFile.value = null
  bundlePreview.value = null
  bundleError.value = ''
}
async function importBundle(): Promise<void> {
  const file = bundleFile.value
  const preview = bundlePreview.value
  if (!file || !preview || bundleBusy.value || !canImport.value) return
  bundleBusy.value = true
  bundleError.value = ''
  try {
    await api.value.importConfigurationBundle(file, preview.bundle_sha256, preview.plan_token, {
      target_ids: preview.target_ids,
      names: bundleNames.value,
      filesystem_bindings: bundleBindings.value,
    })
    bundleFile.value = null
    bundlePreview.value = null
    notify({ tone: 'success', title: t('library.bundle.imported') })
    await refresh()
  } catch (cause) {
    bundleError.value = managementError.describe(cause).display
  } finally {
    bundleBusy.value = false
  }
}

function libraryItemName(item: LibraryItem): string {
  return 'component_name' in item ? item.component_name : item.name
}

async function refresh(): Promise<void> {
  refreshing.value = true
  await Promise.all([libraryTable.value?.reload(), refreshValidationIfOwned()])
  refreshing.value = false
}

function showDetail(item: LibraryItem): void {
  detailMode.value = 'card'
  detailItem.value = item
}

function closeDetail(): void {
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
    } else if (category === 'parent-workflow' || category === 'child-workflow') {
      await api.value.copyWorkflow(source.id, copyName.value)
    } else if (category === 'model-connection') {
      await api.value.copyModelConnection(source.id, copyName.value)
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
    mode: 'local',
    load: async () => {
      const category = currentCategory.value
      if (!category) throw new Error(t('library.unknownCategory', { type: activeCategoryId.value }))
      detailItem.value = null
      copyItem.value = null
      return listCategory(category)
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
      visible: () => currentCategory.value !== 'model-connection',
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
        else if (category === 'parent-workflow' || category === 'child-workflow') await api.value.deleteWorkflow(item.id)
        else if (category === 'model-connection') await api.value.deleteModelConnection(item.id)
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
    label: () => t('common.delete'),
    busyLabel: () => t('common.deleting'),
    icon: 'delete',
    enabled: (context) => currentCategory.value !== 'model-connection' && context.hasAppliedFilters && context.total > 0,
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
      if (category === 'model-connection') return { deleted: 0 }
      const ids = context.matchingRows.map((item) => item.id)
      const result = category === 'main-agent'
        ? await api.value.deleteMainAgents(ids)
        : category === 'subagent-profile'
          ? await api.value.deleteSubagents(ids)
          : category === 'parent-workflow' || category === 'child-workflow'
            ? await api.value.deleteWorkflows(ids)
          : await api.value.deleteBlocks(category, ids)
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
      <input ref="bundleInput" accept=".zip,application/zip" class="visually-hidden" type="file" @change="selectBundle">
      <LteButton v-if="currentCategory !== 'model-connection'" class="action-button" :disabled="bundleBusy" theme="primary" type="button" @click="openBundlePicker">
        <i class="bi bi-upload" aria-hidden="true" />
        {{ t('library.bundle.upload') }}
      </LteButton>
      <LteButton
        class="action-button"
        :disabled="refreshing"
        theme="secondary"
        type="button"
        @click="refresh"
      >
        <span v-if="refreshing" class="spinner-border spinner-border-sm" aria-hidden="true" />
        <i v-else class="bi bi-arrow-clockwise" aria-hidden="true" />
        {{ refreshing ? t('common.refreshing') : t('common.refresh') }}
      </LteButton>
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
              class="action-button"
              v-if="issue.code === 'storage.unknown_block_type' && issue.owner_id && issue.owner_type"
              :disabled="deletingUnsupportedBlockId === issue.owner_id"
              theme="danger"
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
      <LteButton class="action-button" theme="secondary" type="button" @click="closeDetail">
        <i class="bi bi-x-lg" aria-hidden="true" />
        {{ t('common.close') }}
      </LteButton>
      <LteButton
        v-if="detailItem"
        class="action-button"
        theme="secondary"
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

  <ModalHost
    :open="bundlePreview !== null || Boolean(bundleError)"
    size="wide"
    :title="t('library.bundle.previewTitle')"
    @close="closeBundle"
  >
    <LteAlert v-if="bundleError" theme="danger">{{ bundleError }}</LteAlert>
    <template v-if="bundlePreview">
      <p class="small font-monospace text-break">{{ t('library.bundle.digest') }}: {{ bundlePreview.bundle_sha256 }}</p>
      <LteAlert :title="t('library.bundle.securityWarningTitle')" theme="danger">
        {{ t('library.bundle.securityWarning') }}
      </LteAlert>
      <div class="table-responsive mb-3"><table class="table table-striped align-middle"><thead><tr><th>{{ t('library.bundle.originalName') }}</th><th>{{ t('library.bundle.importName') }}</th><th>{{ t('library.bundle.targetId') }}</th></tr></thead><tbody><tr v-for="record in bundlePreview.records" :key="record.source_id"><td>{{ record.original_name }}</td><td><input v-model="bundleNames[record.source_id]" class="form-control" :placeholder="record.requires_confirmation ? record.suggested_name : undefined" required></td><td class="small font-monospace text-break">{{ record.target_id }}</td></tr></tbody></table></div>
      <section v-if="bundlePreview.filesystem_bindings.length" class="mb-3"><h3 class="h5">{{ t('library.bundle.bindings') }}</h3><div v-for="binding in bundlePreview.filesystem_bindings" :key="binding.binding_id" class="row g-3 align-items-end mb-2"><div v-if="binding.kind === 'mapped-directory'" class="col-lg-4"><label class="form-label">{{ t('library.bundle.pathOrigin') }}</label><select v-model="bundleBindings[binding.binding_id]!.path_origin" class="form-select" data-testid="bundle-path-origin"><option disabled value="">{{ t('library.bundle.selectPathOrigin') }}</option><option value="absolute">{{ t('library.bundle.absolute') }}</option><option value="data-root-relative">{{ t('library.bundle.dataRootRelative') }}</option></select></div><div class="col"><label class="form-label">{{ binding.configuration_name }} · {{ binding.path }}</label><input v-model="bundleBindings[binding.binding_id]!.value" class="form-control" data-testid="bundle-binding-value" required></div></div></section>
      <LteAlert v-if="bundleBlockingErrors.length" :title="t('library.bundle.blockers')" theme="danger"><p v-for="issue in bundleBlockingErrors" :key="`${issue.code}:${issue.source_id}:${issue.path}`" class="mb-1">{{ bundleIssueText(issue) }}</p></LteAlert>
      <LteAlert v-if="bundlePreview.warnings.length" :title="t('library.bundle.warnings')" theme="warning"><p v-for="issue in bundlePreview.warnings" :key="`${issue.code}:${issue.source_id}:${issue.path}`" class="mb-1">{{ bundleIssueText(issue) }}</p></LteAlert>
    </template>
    <template #footer><LteButton class="action-button" :disabled="bundleBusy" theme="secondary" type="button" @click="closeBundle"><i class="bi bi-x-lg" aria-hidden="true" />{{ t('common.cancel') }}</LteButton><LteButton class="action-button" :disabled="bundleBusy || !canImport" theme="primary" type="button" @click="importBundle"><span v-if="bundleBusy" class="spinner-border spinner-border-sm" aria-hidden="true" /><i v-else class="bi bi-upload" aria-hidden="true" />{{ t('library.bundle.import') }}</LteButton></template>
  </ModalHost>
</template>
