<script setup lang="ts">
import { LteAlert, LteButton } from '@adminlte/vue'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { managementApi, type ConfigurationBundlePreview } from '@/api'
import ModalHost from '@/components/ModalHost.vue'
import { useManagementError } from '@/composables/useManagementError'
import { useToasts } from '@/composables/useToasts'
import type { ConfigLibraryApi } from '@/pages/configLibrary'

const props = withDefaults(defineProps<{ api?: Pick<ConfigLibraryApi, 'previewConfigurationBundle' | 'importConfigurationBundle'> }>(), {
  api: undefined,
})
const emit = defineEmits<{ imported: [] }>()
const { t, te } = useI18n()
const managementError = useManagementError()
const { notify } = useToasts()
const bundleInput = ref<HTMLInputElement | null>(null)
const bundleFile = ref<File | null>(null)
const bundlePreview = ref<ConfigurationBundlePreview | null>(null)
const bundleNames = ref<Record<string, string>>({})
const bundleBindings = ref<Record<string, { value: string; path_origin?: 'absolute' | 'data-root-relative' }>>({})
const bundleBusy = ref(false)
const bundleError = ref('')

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
  if (preview.records.some((record) => !bundleNames.value[record.source_id]?.trim())) return false
  return preview.filesystem_bindings.every(bindingIsComplete)
})

function bundleIssueText(issue: ConfigurationBundlePreview['errors'][number]): string {
  if (issue.message_key && te(issue.message_key)) return t(issue.message_key, issue.message_args ?? {})
  return t('library.bundle.unknownIssue', { code: issue.code })
}

function openBundlePicker(): void { bundleInput.value?.click() }

async function selectBundle(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  bundleBusy.value = true
  bundleError.value = ''
  try {
    const preview = await (props.api ?? managementApi).previewConfigurationBundle(file)
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
    await (props.api ?? managementApi).importConfigurationBundle(file, preview.bundle_sha256, preview.plan_token, {
      target_ids: preview.target_ids,
      names: bundleNames.value,
      filesystem_bindings: bundleBindings.value,
    })
    closeBundle()
    notify({ tone: 'success', title: t('library.bundle.imported') })
    emit('imported')
  } catch (cause) {
    bundleError.value = managementError.describe(cause).display
  } finally {
    bundleBusy.value = false
  }
}
</script>

<template>
  <input ref="bundleInput" accept=".zip,application/zip" class="visually-hidden" type="file" @change="selectBundle">
  <LteButton class="action-button" :disabled="bundleBusy" type="button" @click="openBundlePicker">
    <i class="bi bi-upload" aria-hidden="true" />
    {{ t('library.bundle.upload') }}
  </LteButton>

  <ModalHost
    :open="bundlePreview !== null || Boolean(bundleError)"
    size="wide"
    :title="t('library.bundle.previewTitle')"
    @close="closeBundle"
  >
    <LteAlert v-if="bundleError" theme="danger">{{ bundleError }}</LteAlert>
    <template v-if="bundlePreview">
      <p class="small font-monospace text-break">{{ t('library.bundle.digest') }}: {{ bundlePreview.bundle_sha256 }}</p>
      <LteAlert :title="t('library.bundle.securityWarningTitle')" theme="danger">{{ t('library.bundle.securityWarning') }}</LteAlert>
      <div class="table-responsive mb-3"><table class="table table-striped align-middle"><thead><tr><th>{{ t('library.bundle.originalName') }}</th><th>{{ t('library.bundle.importName') }}</th><th>{{ t('library.bundle.targetId') }}</th></tr></thead><tbody><tr v-for="record in bundlePreview.records" :key="record.source_id"><td>{{ record.original_name }}</td><td><input v-model="bundleNames[record.source_id]" class="form-control" :placeholder="record.requires_confirmation ? record.suggested_name : undefined" required></td><td class="small font-monospace text-break">{{ record.target_id }}</td></tr></tbody></table></div>
      <section v-if="bundlePreview.filesystem_bindings.length" class="mb-3"><h3 class="h5">{{ t('library.bundle.bindings') }}</h3><div v-for="binding in bundlePreview.filesystem_bindings" :key="binding.binding_id" class="row g-3 align-items-end mb-2"><div v-if="binding.kind === 'mapped-directory'" class="col-lg-4"><label class="form-label">{{ t('library.bundle.pathOrigin') }}</label><select v-model="bundleBindings[binding.binding_id]!.path_origin" class="form-select" data-testid="bundle-path-origin"><option disabled value="">{{ t('library.bundle.selectPathOrigin') }}</option><option value="absolute">{{ t('library.bundle.absolute') }}</option><option value="data-root-relative">{{ t('library.bundle.dataRootRelative') }}</option></select></div><div class="col"><label class="form-label">{{ binding.configuration_name }} · {{ binding.path }}</label><input v-model="bundleBindings[binding.binding_id]!.value" class="form-control" data-testid="bundle-binding-value" required></div></div></section>
      <LteAlert v-if="bundleBlockingErrors.length" :title="t('library.bundle.blockers')" theme="danger"><p v-for="issue in bundleBlockingErrors" :key="`${issue.code}:${issue.source_id}:${issue.path}`" class="mb-1">{{ bundleIssueText(issue) }}</p></LteAlert>
      <LteAlert v-if="bundlePreview.warnings.length" :title="t('library.bundle.warnings')" theme="warning"><p v-for="issue in bundlePreview.warnings" :key="`${issue.code}:${issue.source_id}:${issue.path}`" class="mb-1">{{ bundleIssueText(issue) }}</p></LteAlert>
    </template>
    <template #footer><LteButton class="action-button" :disabled="bundleBusy" type="button" @click="closeBundle"><i class="bi bi-x-lg" aria-hidden="true" />{{ t('common.cancel') }}</LteButton><LteButton class="action-button" :disabled="bundleBusy || !canImport" type="button" @click="importBundle"><span v-if="bundleBusy" class="spinner-border spinner-border-sm" aria-hidden="true" /><i v-else class="bi bi-upload" aria-hidden="true" />{{ t('library.bundle.import') }}</LteButton></template>
  </ModalHost>
</template>
