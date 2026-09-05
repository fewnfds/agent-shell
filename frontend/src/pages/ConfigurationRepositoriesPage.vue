<script setup lang="ts">
import { LteAlert } from '@adminlte/vue'
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { managementApi, type ConfigurationRepository } from '@/api'
import ConfigurationLibraryActions from '@/components/ConfigurationLibraryActions.vue'
import ConfigurationLibraryFrame from '@/components/ConfigurationLibraryFrame.vue'
import CopyNameModal from '@/components/CopyNameModal.vue'
import DataTableWorkbench from '@/components/data-table/DataTableWorkbench.vue'
import type { DataTableConfig } from '@/components/data-table/types'
import PageShell from '@/components/PageShell.vue'
import ValidationChecklist from '@/components/ValidationChecklist.vue'
import { useConfigurationCatalog } from '@/composables/useConfigurationCatalog'
import { useConfigurationValidation } from '@/composables/useConfigurationValidation'
import { useManagementError } from '@/composables/useManagementError'
import { useToasts } from '@/composables/useToasts'
import { triggerBrowserDownload } from '@/utils/download'

const { t } = useI18n()
const managementError = useManagementError()
const { notify } = useToasts()
const table = ref<{ reload: () => Promise<void> } | null>(null)
const refreshing = ref(false)
const copySource = ref<ConfigurationRepository | null>(null)
const copyName = ref('')
const copyError = ref('')
const copying = ref(false)
const {
  manifests,
  error: catalogError,
  load: loadCatalog,
} = useConfigurationCatalog(
  () => managementApi.getCatalog(),
  (error) => managementError.describe(error).display,
)
const { validation: repositoryValidation, validateNow: validateRepository } = useConfigurationValidation({
  buildRequest: () => ({}),
  validate: () => managementApi.validateRepository(),
  errorMessage: (error) => managementError.describe(error, 'errors.validationUnavailable').display,
  immediate: false,
})

function openCopy(repository: ConfigurationRepository): void {
  copySource.value = repository
  copyName.value = ''
  copyError.value = ''
}

function closeCopy(): void {
  if (copying.value) return
  copySource.value = null
  copyName.value = ''
  copyError.value = ''
}

async function refresh(): Promise<void> {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await Promise.all([table.value?.reload(), validateRepository()])
  } finally {
    refreshing.value = false
  }
}

async function copyRepository(): Promise<void> {
  if (!copySource.value || copying.value) return
  const name = copyName.value.trim()
  if (!name) {
    copyError.value = t('configurationRepositories.copy.nameRequired')
    return
  }
  copying.value = true
  copyError.value = ''
  try {
    await managementApi.copyConfigurationRepository(copySource.value.id, name)
    copying.value = false
    closeCopy()
    notify({
      tone: 'success',
      title: t('configurationRepositories.copy.succeeded'),
    })
    await table.value?.reload()
  } catch (error) {
    copyError.value = managementError.describe(error).display
  } finally {
    copying.value = false
  }
}

const tableConfig: DataTableConfig<ConfigurationRepository> = {
  id: 'configuration-repositories',
  ariaLabel: () => t('configurationRepositories.tableAriaLabel'),
  emptyMessage: () => t('configurationRepositories.empty'),
  loadErrorTitle: () => t('configurationRepositories.loadFailed'),
  rowKey: (repository) => repository.id,
  provider: {
    mode: 'local',
    load: async () => (
      await managementApi.listConfigurationRepositories()
    ).repositories,
  },
  search: {
    label: () => t('library.search.label'),
    placeholder: () => t('library.search.placeholder'),
    values: (repository) => [repository.name, repository.id],
  },
  columns: [
    {
      key: 'name',
      label: () => t('configurationRepositories.columns.name'),
      value: (repository) => repository.name,
    },
    {
      key: 'active',
      label: () => t('configurationRepositories.columns.active'),
      value: (repository) => repository.active
        ? t('configurationRepositories.active')
        : t('configurationRepositories.inactive'),
    },
  ],
  rowActions: [
    {
      key: 'activate',
      label: () => t('configurationRepositories.actions.activate'),
      icon: 'activate',
      tone: 'primary',
      visible: (repository) => !repository.active,
      run: (repository) => managementApi.activateConfigurationRepository(repository.id),
      successTitle: () => t('configurationRepositories.activated'),
      failureTitle: () => t('configurationRepositories.activateFailed'),
      reloadAfter: 'current',
    },
    {
      key: 'copy',
      label: () => t('common.copy'),
      icon: 'copy',
      tone: 'secondary',
      run: openCopy,
    },
    {
      key: 'download',
      label: () => t('common.download'),
      icon: 'download',
      tone: 'secondary',
      run: async (repository) => {
        const download = await managementApi.downloadConfigurationRepository(repository.id)
        triggerBrowserDownload(download.blob, download.filename)
      },
      failureTitle: () => t('configurationRepositories.downloadFailed'),
    },
    {
      key: 'delete',
      label: () => t('common.delete'),
      icon: 'delete',
      busyLabel: () => t('common.deleting'),
      tone: 'danger',
      disabled: (repository) => repository.active,
      confirm: (repository) => ({
        title: t('configurationRepositories.delete.title'),
        description: t('configurationRepositories.delete.description', {
          name: repository.name,
        }),
        confirmLabel: t('common.delete'),
        cancelLabel: t('common.cancel'),
        dangerous: true,
      }),
      run: (repository) => managementApi.deleteConfigurationRepository(repository.id),
      successTitle: () => t('configurationRepositories.delete.succeeded'),
      failureTitle: () => t('configurationRepositories.delete.failed'),
      reloadAfter: 'current',
    },
  ],
  pageSize: 20,
  pageSizeOptions: [20, 50, 100],
}

onMounted(() => {
  void Promise.all([validateRepository(), loadCatalog()])
})
</script>

<template>
  <PageShell>
    <template #actions>
      <ConfigurationLibraryActions :refreshing="refreshing" @imported="refresh" @refresh="refresh" />
    </template>
    <ConfigurationLibraryFrame
      :aside-test-id="'configuration-repositories-validation-region'"
      :content-test-id="'configuration-repositories-content-region'"
      :layout-test-id="'configuration-repositories-layout'"
      :manifests="manifests"
    >
      <LteAlert
        v-if="catalogError"
        class="mb-3"
        :title="t('library.catalogUnavailable')"
        theme="danger"
      >
        {{ catalogError }}
      </LteAlert>
      <DataTableWorkbench ref="table" :config="tableConfig">
        <template #cell-active="{ row, value }">
          <span
            class="d-inline-flex align-items-center gap-1"
            :class="row.active ? 'text-success-emphasis' : 'text-body-secondary'"
          >
            <i
              :class="row.active ? 'bi bi-check-circle' : 'bi bi-circle'"
              aria-hidden="true"
            />
            {{ value }}
          </span>
        </template>
      </DataTableWorkbench>
      <template #aside>
        <ValidationChecklist
          :title="t('library.validationTitle')"
          :validation="repositoryValidation"
        />
      </template>
    </ConfigurationLibraryFrame>
  </PageShell>

  <CopyNameModal
    :busy="copying"
    :busy-label="t('common.copying')"
    error-test-id="configuration-repository-copy-error"
    form-id="configuration-repository-copy-form"
    :name="copyName"
    :open="copySource !== null"
    :title="t('configurationRepositories.copy.title')"
    :submit-label="t('common.copy')"
    :error="copyError"
    @close="closeCopy"
    @submit="copyRepository"
    @update:name="copyName = $event"
  />
</template>
