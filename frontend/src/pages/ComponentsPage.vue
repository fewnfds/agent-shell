<script setup lang="ts">
import { LteAlert, LteButton } from '@adminlte/vue'
import { computed, onMounted, ref, watch, type Component } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import {
  managementApi,
  ManagementApiError,
  type BlockPayload,
  type ManagedComponentType,
  type WorkflowComponentManifest,
  type CapabilityManifest,
  type SkillPackageInspection,
  type LocalizedMessagePayload,
  type PythonPackageInspection,
  type SavedBlock,
  type ValidationReport,
} from '@/api'
import PageShell from '@/components/PageShell.vue'
import RecordPicker from '@/components/RecordPicker.vue'
import SectionNav from '@/components/SectionNav.vue'
import type { SectionNavItem } from '@/components/sectionNav'
import ValidationChecklist from '@/components/ValidationChecklist.vue'
import { useConfirmation } from '@/composables/useConfirmation'
import {
  useConfigurationValidation,
  type ConfigurationValidationState,
} from '@/composables/useConfigurationValidation'
import { useManagementError } from '@/composables/useManagementError'
import { useToasts } from '@/composables/useToasts'
import { useUnsavedChanges } from '@/composables/useUnsavedChanges'
import {
  blockAdapters,
  type AgentEventOutputCatalogItem,
  type CommandCatalogItem,
  type TaskDispatcherCatalogItem,
  type BlockDraftBase,
  type CustomMiddlewareCatalogItem,
  type CustomToolCatalogItem,
  type FilesystemImportSource,
  type SkillCatalogItem,
  type WorkflowEventOutputCatalogItem,
} from '@/domain/blocks'
import {
  applyPythonPackageInspection,
  type PythonPackageDraftState,
} from '@/domain/blocks/pythonPackage'
import {
  CustomMiddlewareEditor,
  CustomToolEditor,
  ExceptionRetryEditor,
  FilesystemEditor,
  FilesystemPermissionsEditor,
  ModelRequirementEditor,
  AgentEventOutputEditor,
  PromptCachingEditor,
  SkillEditor,
  SubagentCapabilityEditor,
  SummarizationEditor,
  SystemPromptEditor,
  TodoListEditor,
  WorkflowEventOutputEditor,
  CommandEditor,
  TaskDispatcherEditor,
} from '@/editors'

interface PageBlockAdapter {
  blank(defaults?: unknown): BlockDraftBase
  fromApi(value: SavedBlock, defaults?: unknown): BlockDraftBase
  toPayload(value: BlockDraftBase, defaults?: unknown): BlockPayload
}

const props = withDefaults(defineProps<{
  scope?: 'agent' | 'workflow'
}>(), {
  scope: 'agent',
})

const editorComponents: Record<ManagedComponentType, Component> = {
  'model-requirement': ModelRequirementEditor,
  'system-prompt': SystemPromptEditor,
  filesystem: FilesystemEditor,
  'filesystem-permissions': FilesystemPermissionsEditor,
  'todo-list': TodoListEditor,
  'custom-tool': CustomToolEditor,
  skill: SkillEditor,
  'custom-middleware': CustomMiddlewareEditor,
  'agent-event-output': AgentEventOutputEditor,
  'exception-retry': ExceptionRetryEditor,
  subagent: SubagentCapabilityEditor,
  summarization: SummarizationEditor,
  'prompt-caching': PromptCachingEditor,
  'workflow-event-output': WorkflowEventOutputEditor,
  'command': CommandEditor,
  'task-dispatcher': TaskDispatcherEditor,
}

const { t } = useI18n()
const managementError = useManagementError()
const route = useRoute()
const router = useRouter()
const componentBasePath = computed(() => (
  props.scope === 'workflow' ? '/workflow-components' : '/agent-components'
))
const { confirm } = useConfirmation()
const { notify } = useToasts()

type ManagedManifest = CapabilityManifest | WorkflowComponentManifest
const manifests = ref<ManagedManifest[]>([])
const editorDefaults = ref<Record<string, unknown>>({})
const activeType = ref<ManagedComponentType | null>(null)
const records = ref<SavedBlock[]>([])
const selectedId = ref('')
const draft = ref<BlockDraftBase | null>(null)
const loading = ref(true)
const saving = ref(false)
const pageError = ref('')
const saveValidation = ref<ValidationReport | null>(null)
const storedRecordInvalid = ref(false)

const { markClean, runAfterDiscard } = useUnsavedChanges(
  () => activeType.value && draft.value
    ? payloadFromDraft(activeType.value, draft.value)
    : draft.value,
  () => ({
    title: t('unsavedChanges.title'),
    description: t('unsavedChanges.description'),
    confirmLabel: t('unsavedChanges.confirm'),
    cancelLabel: t('common.cancel'),
  }),
)

const customTools = ref<CustomToolCatalogItem[]>([])
const customToolErrors = ref<Record<string, LocalizedMessagePayload>>({})
const customMiddlewares = ref<CustomMiddlewareCatalogItem[]>([])
const customMiddlewareErrors = ref<Record<string, LocalizedMessagePayload>>({})
const agentEventOutputs = ref<AgentEventOutputCatalogItem[]>([])
const agentEventOutputErrors = ref<Record<string, LocalizedMessagePayload>>({})
const workflowEventOutputs = ref<WorkflowEventOutputCatalogItem[]>([])
const workflowEventOutputErrors = ref<Record<string, LocalizedMessagePayload>>({})
const commandPackages = ref<CommandCatalogItem[]>([])
const commandPackageErrors = ref<Record<string, LocalizedMessagePayload>>({})
const taskDispatcherPackages = ref<TaskDispatcherCatalogItem[]>([])
const taskDispatcherPackageErrors = ref<Record<string, LocalizedMessagePayload>>({})
const skills = ref<SkillCatalogItem[]>([])
const filesystems = ref<FilesystemImportSource[]>([])
const skillErrors = ref<Record<string, LocalizedMessagePayload>>({})
const privateSkillPackage = ref<SkillPackageInspection | null>(null)
const privateSkillLoading = ref(false)
const privateSkillMutating = ref(false)
const loadingResource = ref(false)

let routeSequence = 0
let catalogSequence = 0
let resourceSequence = 0
let privateSkillSequence = 0
let privateSkillLoadingSequence = 0
let privateSkillMutationSequence = 0

function invalidateResourceRequests(): void {
  resourceSequence += 1
  privateSkillSequence += 1
  loadingResource.value = false
  privateSkillLoading.value = false
  privateSkillMutating.value = false
}

function resourceRequestIsCurrent(
  sequence: number,
  type: ManagedComponentType | null,
): boolean {
  return sequence === resourceSequence && activeType.value === type
}

function privateSkillRequestIsCurrent(sequence: number, ownerId: string): boolean {
  return (
    sequence === privateSkillSequence
    && activeType.value === 'skill'
    && draft.value?.id === ownerId
  )
}

function defaultsForType(type: ManagedComponentType | null): unknown {
  const editorKey = manifests.value.find((item) => item.type === type)?.editor_key
  return editorKey ? editorDefaults.value[editorKey] : undefined
}

const activeDefaults = computed(() => defaultsForType(activeType.value))
const currentEditor = computed(() => activeType.value ? editorComponents[activeType.value] : null)
const navigationItems = computed<SectionNavItem[]>(() => manifests.value.map((manifest) => ({
  id: manifest.type,
  label: t(`capabilities.${manifest.type}.label`),
})))

const editorProps = computed<Record<string, unknown>>(() => {
  switch (activeType.value) {
    case 'custom-tool':
      return {
        catalog: customTools.value,
        errors: customToolErrors.value,
        loading: loadingResource.value,
      }
    case 'custom-middleware':
      return {
        catalog: customMiddlewares.value,
        errors: customMiddlewareErrors.value,
        loading: loadingResource.value,
      }
    case 'agent-event-output':
      return {
        catalog: agentEventOutputs.value,
        errors: agentEventOutputErrors.value,
        loading: loadingResource.value,
      }
    case 'workflow-event-output':
      return {
        catalog: workflowEventOutputs.value,
        errors: workflowEventOutputErrors.value,
        loading: loadingResource.value,
      }
    case 'command':
      return {
        defaults: activeDefaults.value,
        catalog: commandPackages.value,
        errors: commandPackageErrors.value,
        loading: loadingResource.value,
      }
    case 'task-dispatcher':
      return {
        defaults: activeDefaults.value,
        catalog: taskDispatcherPackages.value,
        errors: taskDispatcherPackageErrors.value,
        loading: loadingResource.value,
      }
    case 'skill':
      return {
        defaults: activeDefaults.value,
        catalog: skills.value,
        errors: skillErrors.value,
        loading: loadingResource.value,
        privatePackage: privateSkillPackage.value,
        privateLoading: privateSkillLoading.value,
        mutating: privateSkillMutating.value,
      }
    case 'filesystem':
    case 'filesystem-permissions':
    case 'todo-list':
    case 'exception-retry':
    case 'subagent':
    case 'summarization':
    case 'prompt-caching':
      return {
        defaults: activeDefaults.value,
        ...(activeType.value === 'filesystem-permissions'
          ? { filesystems: filesystems.value }
          : {}),
      }
    default:
      return {}
  }
})

function adapter(type: ManagedComponentType): PageBlockAdapter {
  return blockAdapters[type] as unknown as PageBlockAdapter
}

function blankDraft(type: ManagedComponentType): BlockDraftBase {
  return adapter(type).blank(defaultsForType(type))
}

function draftFromApi(type: ManagedComponentType, value: SavedBlock): BlockDraftBase {
  return adapter(type).fromApi(value, defaultsForType(type))
}

function payloadFromDraft(type: ManagedComponentType, value: BlockDraftBase): BlockPayload {
  return adapter(type).toPayload(value, defaultsForType(type))
}

function usesPythonExtension(type: ManagedComponentType): boolean {
  return (
    type === 'custom-tool'
    || type === 'custom-middleware'
    || type === 'agent-event-output'
    || type === 'workflow-event-output'
    || type === 'command'
    || type === 'task-dispatcher'
  )
}

function validationPayloadFromDraft(
  type: ManagedComponentType,
  value: BlockDraftBase,
): BlockPayload | null {
  const payload = payloadFromDraft(type, value)
  if (type === 'skill' && !value.id) return null
  if (!usesPythonExtension(type)) return payload
  if (!value.id) return null
  return payload
}

function routeId(): string {
  return typeof route.query.id === 'string' ? route.query.id : ''
}

function notifyFailure(titleKey: string, error: unknown): void {
  notify({
    tone: 'danger',
    title: t(titleKey),
    message: managementError.describe(error).display,
  })
}

async function isStoredRecordInvalid(id: string): Promise<boolean> {
  try {
    const report = await managementApi.validateRepository()
    return report.issues.some((issue) => issue.scope === 'block' && issue.owner_id === id)
  } catch {
    return false
  }
}

const { validation } = useConfigurationValidation({
  source: draft,
  buildRequest: () => {
    if (!activeType.value || !draft.value) return null
    const payload = validationPayloadFromDraft(activeType.value, draft.value)
    if (payload === null) return null
    return {
      target: {
        kind: 'block',
        type: activeType.value,
        id: draft.value.id,
      },
      payload,
    }
  },
  validate: (request) => managementApi.validateDraft(request),
  errorMessage: (error) => managementError.describe(
    error,
    'errors.validationUnavailable',
  ).display,
})

const displayedValidation = computed<ConfigurationValidationState>(() => {
  if (saveValidation.value) return { status: 'invalid', report: saveValidation.value, error: '' }
  return validation.value
})

const showDraftValidation = computed(() => (
  saveValidation.value !== null
  || !activeType.value
  || !draft.value
  || !usesPythonExtension(activeType.value)
  && activeType.value !== 'skill'
  || Boolean(draft.value.id)
))

watch(draft, () => {
  saveValidation.value = null
}, { deep: true })

async function loadRoute(): Promise<void> {
  if (manifests.value.length === 0) return
  const requestedType = typeof route.params.type === 'string' ? route.params.type : ''
  const manifest = manifests.value.find((item) => item.type === requestedType)
  if (!manifest) {
    const fallback = manifests.value[0]
    if (fallback) await router.replace({ path: `${componentBasePath.value}/${fallback.type}` })
    return
  }

  routeSequence += 1
  const sequence = routeSequence
  invalidateResourceRequests()
  loading.value = true
  pageError.value = ''
  saveValidation.value = null
  try {
    const [listed, filesystemItems] = await Promise.all([
      managementApi.listBlocks(manifest.type),
      manifest.type === 'filesystem-permissions'
        ? managementApi.listBlocks('filesystem')
        : Promise.resolve([]),
    ])
    if (sequence !== routeSequence) return
    const id = routeId()
    let loadedDraft: BlockDraftBase
    if (id) {
      const [loaded, invalid, packageInspection] = await Promise.all([
        managementApi.getBlock(manifest.type, id),
        isStoredRecordInvalid(id),
        usesPythonExtension(manifest.type)
          ? managementApi.inspectPythonPackage(manifest.type, id)
          : Promise.resolve(null),
      ])
      if (sequence !== routeSequence) return
      loadedDraft = draftFromApi(manifest.type, loaded)
      if (packageInspection) {
        applyPythonPackageInspection(
          loadedDraft as BlockDraftBase & PythonPackageDraftState,
          packageInspection,
        )
      }
      privateSkillPackage.value = manifest.type === 'skill'
        ? ((loaded as SavedBlock & { skill_package_contents?: SkillPackageInspection }).skill_package_contents ?? null)
        : null
      storedRecordInvalid.value = invalid
    } else {
      loadedDraft = blankDraft(manifest.type)
      privateSkillPackage.value = null
      storedRecordInvalid.value = false
    }
    activeType.value = manifest.type
    records.value = listed
    filesystems.value = filesystemItems as FilesystemImportSource[]
    draft.value = loadedDraft
    selectedId.value = loadedDraft.id
    markClean()
    if (manifest.type === 'skill' || (!id && usesPythonExtension(manifest.type))) {
      await refreshResource()
    }
  } catch (error) {
    if (sequence !== routeSequence) return
    pageError.value = managementError.describe(error).display
  } finally {
    if (sequence === routeSequence) loading.value = false
  }
}

async function loadCatalog(): Promise<void> {
  catalogSequence += 1
  const sequence = catalogSequence
  const scope = props.scope
  loading.value = true
  pageError.value = ''
  try {
    const catalog = await managementApi.getCatalog()
    if (sequence !== catalogSequence || scope !== props.scope) return
    manifests.value = (
      scope === 'workflow'
        ? catalog.workflow_component_types
        : catalog.block_types
    ).slice().sort((left, right) => left.order - right.order)
    editorDefaults.value = catalog.editor_defaults
    await loadRoute()
  } catch (error) {
    if (sequence !== catalogSequence || scope !== props.scope) return
    pageError.value = managementError.describe(error).display
    loading.value = false
  }
}

async function selectType(type: string): Promise<void> {
  await runAfterDiscard(async () => {
    await router.push({ path: `${componentBasePath.value}/${type}` })
  })
}

async function selectRecord(id: string): Promise<void> {
  if (!activeType.value) return
  await runAfterDiscard(async () => {
    await router.push({
      path: `${componentBasePath.value}/${activeType.value}`,
      ...(id ? { query: { id } } : {}),
    })
  })
}

async function startNew(): Promise<void> {
  if (!activeType.value) return
  await runAfterDiscard(async () => {
    await router.push({ path: `${componentBasePath.value}/${activeType.value}` })
    if (!routeId()) {
      selectedId.value = ''
      draft.value = blankDraft(activeType.value!)
      storedRecordInvalid.value = false
      markClean()
      if (activeType.value === 'skill' || usesPythonExtension(activeType.value!)) {
        await refreshResource()
      }
    }
  })
}

async function reset(): Promise<void> {
  if (!activeType.value) return
  await runAfterDiscard(async () => {
    saveValidation.value = null
    try {
      if (draft.value?.id) {
        const id = draft.value.id
        const [loaded, invalid, packageInspection] = await Promise.all([
          managementApi.getBlock(activeType.value!, id),
          isStoredRecordInvalid(id),
          usesPythonExtension(activeType.value!)
            ? managementApi.inspectPythonPackage(activeType.value!, id)
            : Promise.resolve(null),
        ])
        const loadedDraft = draftFromApi(activeType.value!, loaded)
        if (packageInspection) {
          applyPythonPackageInspection(
            loadedDraft as BlockDraftBase & PythonPackageDraftState,
            packageInspection,
          )
        }
        draft.value = loadedDraft
        storedRecordInvalid.value = invalid
      } else {
        draft.value = blankDraft(activeType.value!)
        storedRecordInvalid.value = false
      }
      markClean()
      notify({ tone: 'info', title: t('components.feedback.reset') })
    } catch (error) {
      notifyFailure('components.feedback.resetFailed', error)
    }
  })
}

function upsertRecord(saved: SavedBlock): void {
  const index = records.value.findIndex((item) => item.id === saved.id)
  if (index === -1) records.value.push(saved)
  else records.value[index] = saved
}

async function save(): Promise<void> {
  if (!activeType.value || !draft.value) return
  pageError.value = ''
  const packageType = usesPythonExtension(activeType.value)
  const privateAssetType = packageType || activeType.value === 'skill'
  const packageDraft = packageType
    ? draft.value as BlockDraftBase & PythonPackageDraftState
    : null
  if (
    packageDraft
    && !packageDraft.id
    && !packageDraft.python_package_template.key.trim()
  ) {
    pageError.value = t('errors.pythonPackageTemplateRequired')
    return
  }
  const payload = payloadFromDraft(activeType.value, draft.value)
  const existing = records.value.find((record) => (
    record.name === payload.name && record.id !== draft.value?.id
  ))
  let targetId = draft.value.id
  if (existing) {
    if (privateAssetType) {
      pageError.value = t('errors.configurationNameConflict')
      return
    }
    const accepted = await confirm({
      title: t('components.overwrite.title'),
      description: t('components.overwrite.description', { name: existing.name }),
      confirmLabel: t('components.overwrite.confirm'),
      cancelLabel: t('common.cancel'),
      dangerous: true,
    })
    if (!accepted) return
    targetId = existing.id
  }

  saving.value = true
  saveValidation.value = null
  try {
    const request = targetId ? { id: targetId, ...payload } : payload
    const saved = await managementApi.saveBlock(activeType.value, request)
    const savedDraft = draftFromApi(activeType.value, saved)
    if (packageType) {
      applyPythonPackageInspection(
        savedDraft as BlockDraftBase & PythonPackageDraftState,
        await managementApi.inspectPythonPackage(activeType.value, saved.id),
      )
    }
    draft.value = savedDraft
    privateSkillPackage.value = activeType.value === 'skill'
      ? ((saved as SavedBlock & { skill_package_contents?: SkillPackageInspection }).skill_package_contents ?? null)
      : null
    storedRecordInvalid.value = false
    selectedId.value = saved.id
    upsertRecord(saved)
    markClean()
    await router.replace({
      path: `${componentBasePath.value}/${activeType.value}`,
      query: { id: saved.id },
    })
    notify({ tone: 'success', title: t('components.feedback.saved') })
  } catch (error) {
    if (error instanceof ManagementApiError && error.validation) {
      saveValidation.value = error.validation
    } else {
      notifyFailure('components.feedback.saveFailed', error)
    }
  } finally {
    saving.value = false
  }
}

function updateDraft(value: BlockDraftBase): void {
  draft.value = value
}

async function refreshResource(): Promise<void> {
  const type = activeType.value
  const ownerId = draft.value?.id ?? ''
  resourceSequence += 1
  const sequence = resourceSequence
  loadingResource.value = true
  try {
    if (type && usesPythonExtension(type) && ownerId) {
      const inspection: PythonPackageInspection = await managementApi.inspectPythonPackage(
        type,
        ownerId,
      )
      if (resourceRequestIsCurrent(sequence, type) && draft.value?.id === ownerId) {
        applyPythonPackageInspection(
          draft.value as BlockDraftBase & PythonPackageDraftState,
          inspection,
        )
      }
    } else if (type === 'custom-tool') {
      const result = await managementApi.listCustomToolTemplates()
      if (!resourceRequestIsCurrent(sequence, type)) return
      customTools.value = result.catalog
      customToolErrors.value = result.errors
    } else if (type === 'custom-middleware') {
      const result = await managementApi.listMiddlewareTemplates()
      if (!resourceRequestIsCurrent(sequence, type)) return
      customMiddlewares.value = result.catalog
      customMiddlewareErrors.value = result.errors
    } else if (type === 'agent-event-output') {
      const result = await managementApi.listAgentEventOutputTemplates()
      if (!resourceRequestIsCurrent(sequence, type)) return
      agentEventOutputs.value = result.catalog
      agentEventOutputErrors.value = result.errors
    } else if (type === 'workflow-event-output') {
      const result = await managementApi.listWorkflowEventOutputTemplates()
      if (!resourceRequestIsCurrent(sequence, type)) return
      workflowEventOutputs.value = result.catalog
      workflowEventOutputErrors.value = result.errors
    } else if (type === 'command') {
      const result = await managementApi.listCommandTemplates()
      if (!resourceRequestIsCurrent(sequence, type)) return
      commandPackages.value = result.catalog
      commandPackageErrors.value = result.errors
    } else if (type === 'task-dispatcher') {
      const result = await managementApi.listTaskDispatcherTemplates()
      if (!resourceRequestIsCurrent(sequence, type)) return
      taskDispatcherPackages.value = result.catalog
      taskDispatcherPackageErrors.value = result.errors
    } else if (type === 'skill') {
      const result = await managementApi.listSkills()
      if (!resourceRequestIsCurrent(sequence, type)) return
      skills.value = result.catalog
      skillErrors.value = result.errors
      if (ownerId) await refreshPrivateSkillPackage(ownerId)
    }
  } catch (error) {
    if (resourceRequestIsCurrent(sequence, type)) {
      notifyFailure('components.feedback.resourceFailed', error)
    }
  } finally {
    if (sequence === resourceSequence) loadingResource.value = false
  }
}

async function refreshPrivateSkillPackage(ownerId: string): Promise<void> {
  privateSkillSequence += 1
  const sequence = privateSkillSequence
  privateSkillLoadingSequence = sequence
  privateSkillLoading.value = true
  try {
    const inspection = await managementApi.inspectPrivateSkills(ownerId)
    if (privateSkillRequestIsCurrent(sequence, ownerId)) {
      privateSkillPackage.value = inspection
    }
  } catch (error) {
    if (privateSkillRequestIsCurrent(sequence, ownerId)) {
      notifyFailure('components.feedback.resourceFailed', error)
    }
  } finally {
    if (privateSkillLoadingSequence === sequence) {
      privateSkillLoading.value = false
    }
  }
}

async function addPrivateSkill(templatePath: string): Promise<void> {
  if (activeType.value !== 'skill' || !draft.value?.id) return
  const ownerId = draft.value.id
  privateSkillSequence += 1
  const sequence = privateSkillSequence
  privateSkillMutationSequence = sequence
  privateSkillMutating.value = true
  try {
    const inspection = await managementApi.addPrivateSkill(ownerId, templatePath)
    if (privateSkillRequestIsCurrent(sequence, ownerId)) {
      privateSkillPackage.value = inspection
    }
  } catch (error) {
    if (privateSkillRequestIsCurrent(sequence, ownerId)) {
      notifyFailure('components.feedback.resourceFailed', error)
    }
  } finally {
    if (privateSkillMutationSequence === sequence) {
      privateSkillMutating.value = false
    }
  }
}

async function removePrivateSkill(folder: string): Promise<void> {
  if (activeType.value !== 'skill' || !draft.value?.id) return
  const ownerId = draft.value.id
  privateSkillSequence += 1
  const sequence = privateSkillSequence
  privateSkillMutationSequence = sequence
  privateSkillMutating.value = true
  try {
    const inspection = await managementApi.deletePrivateSkill(ownerId, folder)
    if (privateSkillRequestIsCurrent(sequence, ownerId)) {
      privateSkillPackage.value = inspection
    }
  } catch (error) {
    if (privateSkillRequestIsCurrent(sequence, ownerId)) {
      notifyFailure('components.feedback.resourceFailed', error)
    }
  } finally {
    if (privateSkillMutationSequence === sequence) {
      privateSkillMutating.value = false
    }
  }
}

watch(
  () => [props.scope, route.params.type, route.query.id] as const,
  ([scope], [previousScope]) => {
    if (scope !== previousScope) {
      routeSequence += 1
      invalidateResourceRequests()
      manifests.value = []
      activeType.value = null
      records.value = []
      selectedId.value = ''
      draft.value = null
      privateSkillPackage.value = null
      markClean()
      void loadCatalog()
      return
    }
    if (manifests.value.length === 0) return
    const requestedType = typeof route.params.type === 'string' ? route.params.type : ''
    if (requestedType === activeType.value && routeId() === (draft.value?.id ?? '')) return
    void loadRoute()
  },
)

onMounted(() => {
  void loadCatalog()
})
</script>

<template>
  <PageShell>
    <template #actions>
      <LteButton
        :disabled="!draft || loading"
        theme="success"
        type="button"
        @click="startNew"
      >
        {{ t('common.new') }}
      </LteButton>
      <LteButton
        :disabled="!draft || loading"
        theme="warning"
        type="button"
        @click="reset"
      >
        {{ t('common.reset') }}
      </LteButton>
      <LteButton
        :disabled="!draft || loading || saving"
        theme="primary"
        type="button"
        @click="save"
      >
        <span v-if="saving" class="spinner-border spinner-border-sm" aria-hidden="true" />
        {{ t('common.save') }}
      </LteButton>
    </template>

    <template #status>
      <LteAlert
        v-if="pageError"
        data-testid="page-error"
        :title="t('components.feedback.requestFailed')"
        theme="danger"
      >
        {{ pageError }}
      </LteAlert>
    </template>

    <SectionNav
      v-if="props.scope === 'agent' && navigationItems.length"
      :active-id="activeType ?? ''"
      :aria-label="t('components.navigationLabel')"
      class="mb-3"
      :items="navigationItems"
      layout="inline"
      @select="selectType"
    />

    <div
      v-if="activeType && draft"
      class="row g-3 align-items-start configuration-loading-surface"
      data-testid="component-layout"
      :aria-busy="loading"
      :data-loading="loading"
      :inert="loading || undefined"
    >
      <section class="col-lg-9 component-editor-region" data-testid="editor-region">
        <LteAlert
          v-if="storedRecordInvalid"
          class="mb-3"
          data-testid="stored-invalid-warning"
          :title="t('components.storedInvalidWarning')"
          theme="warning"
        />
        <div class="mb-3">
          <RecordPicker
            :model-value="selectedId"
            :name="draft.name"
            :records="records"
            :disabled="loading"
            @select="selectRecord"
            @update:name="draft.name = $event"
          />
        </div>

      <component
          :is="currentEditor"
          v-bind="editorProps"
          :model-value="draft"
          @refresh="refreshResource"
          @add-skill="addPrivateSkill"
          @remove-skill="removePrivateSkill"
          @update:model-value="updateDraft"
        />
      </section>

      <aside class="col-lg-3 validation-sidebar" data-testid="inspector-region">
        <ValidationChecklist
          v-if="showDraftValidation"
          :title="t('validation.draftTitle')"
          :validation="displayedValidation"
        />
      </aside>
    </div>
  </PageShell>
</template>
