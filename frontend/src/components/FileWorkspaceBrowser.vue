<script setup lang="ts">
import { LteAlert, LteButton, LteProgress } from '@adminlte/vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  ManagementApiError,
  managementApi,
  type ManagedArchivePreview,
  type ManagedDirectory,
  type ManagedFileItem,
  type ManagedFileUploadResult,
} from '@/api'
import { useConfirmation } from '@/composables/useConfirmation'
import { useManagementError } from '@/composables/useManagementError'
import { useToasts } from '@/composables/useToasts'
import { formattingLocale } from '@/locales'
import { triggerBrowserDownload } from '@/utils/download'

interface FileWorkspaceApi {
  listManagedFiles(path?: string): Promise<ManagedDirectory>
  createManagedDirectory(path: string): Promise<{ path: string }>
  createManagedTextFile(path: string): Promise<{ path: string }>
  uploadManagedFile(
    path: string,
    file: Blob,
    overwrite: boolean,
    onProgress?: (loaded: number, total: number) => void,
  ): Promise<ManagedFileUploadResult>
  downloadManagedEntry(path: string): Promise<Blob>
  previewManagedArchive(paths: string[]): Promise<ManagedArchivePreview>
  downloadManagedArchive(paths: string[]): Promise<Blob>
  renameManagedEntry(path: string, name: string): Promise<{ path: string }>
  deleteManagedFile(path: string): Promise<{ deleted: boolean }>
}

interface UploadItem {
  id: string
  file: File
  path: string
  progress: number
  status: 'pending' | 'uploading' | 'completed' | 'failed'
  error: string
}

const props = withDefaults(defineProps<{
  initialPath?: string
  highlightedPath?: string
  api?: FileWorkspaceApi
}>(), {
  initialPath: 'data',
  highlightedPath: '',
  api: undefined,
})
const emit = defineEmits<{
  'open-file': [path: string]
  changed: []
}>()

const api = props.api ?? managementApi
const { locale, t } = useI18n()
const confirmation = useConfirmation()
const managementError = useManagementError()
const { notify } = useToasts()

const directory = ref<ManagedDirectory | null>(null)
const loading = ref(false)
const pageError = ref('')
const selectedItems = ref<ManagedFileItem[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const folderInput = ref<HTMLInputElement | null>(null)
const uploads = ref<UploadItem[]>([])
const uploading = ref(false)
const archiveDownloading = ref(false)
const createOpen = ref(false)
const createKind = ref<'directory' | 'file'>('directory')
const createName = ref('')
const createSaving = ref(false)
const renameOpen = ref(false)
const renamingItem = ref<ManagedFileItem | null>(null)
const renameName = ref('')
const renameSaving = ref(false)
let requestSequence = 0

const breadcrumbs = computed(() => {
  const parts = (directory.value?.path ?? props.initialPath).split('/')
  return parts.map((label, index) => ({
    label,
    path: parts.slice(0, index + 1).join('/'),
  }))
})
const selectableItems = computed(() => (
  directory.value?.items.filter((item) => item.capabilities.archive) ?? []
))
const allSelected = computed(() => (
  selectableItems.value.length > 0
  && selectableItems.value.every((item) => isSelected(item))
))

function joinPath(base: string, child: string): string {
  return `${base}/${child}`
}

async function load(path = directory.value?.path ?? props.initialPath): Promise<void> {
  const sequence = ++requestSequence
  loading.value = true
  pageError.value = ''
  selectedItems.value = []
  try {
    const response = await api.listManagedFiles(path)
    if (sequence !== requestSequence) return
    directory.value = response
  } catch (error) {
    if (sequence !== requestSequence) return
    pageError.value = managementError.describe(error).display
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

function openItem(item: ManagedFileItem): void {
  if (item.kind === 'directory' && item.capabilities.list) {
    void load(item.path)
  } else if (item.kind === 'file' && item.capabilities.read) {
    emit('open-file', item.path)
  }
}

function openCreate(kind: 'directory' | 'file'): void {
  renameOpen.value = false
  createKind.value = kind
  createName.value = ''
  createOpen.value = true
}

async function createEntry(): Promise<void> {
  const name = createName.value.trim()
  if (!directory.value || !name) return
  createSaving.value = true
  pageError.value = ''
  try {
    const path = joinPath(directory.value.path, name)
    if (createKind.value === 'directory') await api.createManagedDirectory(path)
    else await api.createManagedTextFile(path)
    createOpen.value = false
    emit('changed')
    await load()
  } catch (error) {
    pageError.value = managementError.describe(error).display
  } finally {
    createSaving.value = false
  }
}

function selectFiles(event: Event): void {
  if (!directory.value) return
  const input = event.target as HTMLInputElement
  const selected = Array.from(input.files ?? [])
  input.value = ''
  if (!selected.length) return
  uploads.value = selected.map((file, index) => ({
    id: `${Date.now()}-${index}-${file.name}`,
    file,
    path: joinPath(directory.value!.path, file.webkitRelativePath || file.name),
    progress: 0,
    status: 'pending',
    error: '',
  }))
  void runUploads()
}

async function runUploads(): Promise<void> {
  if (uploading.value) return
  uploading.value = true
  let completed = 0
  for (const item of uploads.value) {
    item.status = 'uploading'
    try {
      await api.uploadManagedFile(item.path, item.file, false, (loaded, total) => {
        item.progress = total > 0 ? Math.round((loaded / total) * 100) : 0
      })
      item.progress = 100
      item.status = 'completed'
      completed += 1
    } catch (caught) {
      let error: unknown = caught
      let overwrite = false
      if (caught instanceof ManagementApiError && caught.code === 'file_already_exists') {
        overwrite = await confirmation.confirm({
          title: t('fileManager.overwrite.title'),
          description: t('fileManager.overwrite.description', { path: item.path }),
          confirmLabel: t('fileManager.overwrite.confirm'),
          cancelLabel: t('common.cancel'),
          dangerous: true,
        })
      }
      if (overwrite) {
        try {
          await api.uploadManagedFile(item.path, item.file, true)
          item.progress = 100
          item.status = 'completed'
          completed += 1
          continue
        } catch (retryError) {
          error = retryError
        }
      }
      item.status = 'failed'
      item.error = managementError.describe(error).display
    }
  }
  uploading.value = false
  if (completed) emit('changed')
  await load()
  notify({
    tone: completed === uploads.value.length ? 'success' : 'danger',
    title: t('fileManager.upload.completed', { count: completed, total: uploads.value.length }),
  })
}

function startRename(item: ManagedFileItem): void {
  createOpen.value = false
  renamingItem.value = item
  renameName.value = item.name
  renameOpen.value = true
}

async function renameItem(): Promise<void> {
  const name = renameName.value.trim()
  if (!renamingItem.value || !name) return
  renameSaving.value = true
  try {
    await api.renameManagedEntry(renamingItem.value.path, name)
    renameOpen.value = false
    emit('changed')
    await load()
  } catch (error) {
    pageError.value = managementError.describe(error).display
  } finally {
    renameSaving.value = false
  }
}

async function removeItem(item: ManagedFileItem): Promise<void> {
  const accepted = await confirmation.confirm({
    title: t('fileManager.delete.title'),
    description: t('fileManager.delete.description', { name: item.name }),
    confirmLabel: t('common.delete'),
    cancelLabel: t('common.cancel'),
    dangerous: true,
  })
  if (!accepted) return
  try {
    await api.deleteManagedFile(item.path)
    emit('changed')
    await load()
  } catch (error) {
    pageError.value = managementError.describe(error).display
  }
}

async function download(item: ManagedFileItem): Promise<void> {
  try {
    const blob = await api.downloadManagedEntry(item.path)
    triggerBrowserDownload(blob, item.kind === 'directory' ? `${item.name}.zip` : item.name)
  } catch (error) {
    pageError.value = managementError.describe(error).display
  }
}

function isSelected(item: ManagedFileItem): boolean {
  return selectedItems.value.some((selected) => selected.path === item.path)
}

function toggleSelection(item: ManagedFileItem, event: Event): void {
  selectedItems.value = (event.target as HTMLInputElement).checked
    ? [...selectedItems.value, item]
    : selectedItems.value.filter((selected) => selected.path !== item.path)
}

function toggleAll(event: Event): void {
  selectedItems.value = (event.target as HTMLInputElement).checked
    ? [...selectableItems.value]
    : []
}

async function downloadArchive(): Promise<void> {
  if (!selectedItems.value.length || archiveDownloading.value) return
  archiveDownloading.value = true
  try {
    const paths = selectedItems.value.map((item) => item.path)
    const preview = await api.previewManagedArchive(paths)
    const accepted = await confirmation.confirm({
      title: t('fileManager.archive.confirmTitle'),
      description: t('fileManager.archive.confirmDescription', {
        fileCount: preview.file_count,
        directoryCount: preview.directory_count,
        size: formatSize(preview.total_size),
      }),
      confirmLabel: t('fileManager.archive.confirm'),
      cancelLabel: t('common.cancel'),
    })
    if (!accepted) return
    triggerBrowserDownload(await api.downloadManagedArchive(paths), 'agent-shell-files.zip')
  } catch (error) {
    pageError.value = managementError.describe(error).display
  } finally {
    archiveDownloading.value = false
  }
}

function formatSize(value: number | null): string {
  if (value === null) return '-'
  return new Intl.NumberFormat(formattingLocale(locale.value), {
    style: 'unit',
    unit: value >= 1024 * 1024 ? 'megabyte' : value >= 1024 ? 'kilobyte' : 'byte',
    unitDisplay: 'short',
    maximumFractionDigits: 1,
  }).format(value >= 1024 * 1024 ? value / (1024 * 1024) : value >= 1024 ? value / 1024 : value)
}

function formatTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(
    formattingLocale(locale.value),
    { dateStyle: 'short', timeStyle: 'short' },
  ).format(date)
}

watch(() => props.initialPath, (path) => { void load(path) })
onMounted(() => { void load(props.initialPath) })
defineExpose({ refresh: load })
</script>

<template>
  <section>
    <div class="d-flex flex-wrap align-items-center gap-2 mb-3">
      <LteButton class="action-button" :disabled="loading" type="button" @click="load()">
        <i class="bi bi-arrow-clockwise" aria-hidden="true" />
        {{ t('common.refresh') }}
      </LteButton>
      <template v-if="directory?.capabilities.create">
        <LteButton class="action-button" type="button" @click="openCreate('directory')">
          <i class="bi bi-folder-plus" aria-hidden="true" />
          {{ t('fileManager.createFolder') }}
        </LteButton>
        <LteButton class="action-button" type="button" @click="openCreate('file')">
          <i class="bi bi-file-earmark-plus" aria-hidden="true" />
          {{ t('fileManager.createFile') }}
        </LteButton>
      </template>
      <template v-if="directory?.capabilities.upload">
        <LteButton class="action-button" :disabled="uploading" type="button" @click="fileInput?.click()">
          <i class="bi bi-upload" aria-hidden="true" />
          {{ t('fileManager.uploadFiles') }}
        </LteButton>
        <LteButton class="action-button" :disabled="uploading" type="button" @click="folderInput?.click()">
          <i class="bi bi-folder-plus" aria-hidden="true" />
          {{ t('fileManager.uploadFolder') }}
        </LteButton>
      </template>
      <LteButton
        class="action-button ms-auto"
        :disabled="!selectedItems.length || archiveDownloading"
        type="button"
        @click="downloadArchive"
      >
        <i class="bi bi-archive" aria-hidden="true" />
        {{ t('fileManager.archive.selected', { count: selectedItems.length }) }}
      </LteButton>
      <input ref="fileInput" class="d-none" multiple type="file" @change="selectFiles">
      <input ref="folderInput" class="d-none" multiple type="file" webkitdirectory @change="selectFiles">
    </div>

    <nav :aria-label="t('fileManager.breadcrumb')" class="mb-3">
      <ol class="breadcrumb flex-wrap mb-0">
        <li
          v-for="(item, index) in breadcrumbs"
          :key="item.path"
          class="breadcrumb-item"
          :aria-current="index === breadcrumbs.length - 1 ? 'page' : undefined"
        >
          <a
            v-if="index < breadcrumbs.length - 1"
            class="text-decoration-none"
            href="#"
            @click.prevent="load(item.path)"
          >
            {{ item.label }}
          </a>
          <span v-else>{{ item.label }}</span>
        </li>
      </ol>
    </nav>

    <LteAlert v-if="pageError" class="mb-3" theme="danger" :title="t('fileManager.requestFailed')">
      {{ pageError }}
    </LteAlert>

    <div v-if="uploads.length" class="mb-3">
      <div v-for="item in uploads" :key="item.id" class="mb-2">
        <div class="d-flex gap-2 small">
          <span class="text-break">{{ item.path }}</span>
          <span class="ms-auto">{{ t(`fileManager.upload.status.${item.status}`) }}</span>
        </div>
        <LteProgress :value="item.progress" />
        <div v-if="item.error" class="small text-danger">{{ item.error }}</div>
      </div>
    </div>

    <div v-if="loading" class="d-flex align-items-center gap-2 p-3" role="status">
      <span class="spinner-border" aria-hidden="true" />
      <span>{{ t('common.loading') }}</span>
    </div>
    <div v-else class="table-responsive">
      <table class="table table-hover align-middle">
        <thead class="management-table-head">
          <tr>
            <th>
              <input
                :aria-label="t('fileManager.selectAll')"
                :checked="allSelected"
                class="form-check-input"
                type="checkbox"
                @change="toggleAll"
              >
            </th>
            <th>{{ t('fileManager.columns.name') }}</th>
            <th>{{ t('fileManager.columns.kind') }}</th>
            <th>{{ t('fileManager.columns.size') }}</th>
            <th>{{ t('fileManager.columns.modified') }}</th>
            <th class="text-end">{{ t('fileManager.columns.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="directory?.items.length === 0">
            <td class="p-3 text-center text-body-secondary" colspan="6">{{ t('fileManager.empty') }}</td>
          </tr>
          <tr
            v-for="item in directory?.items ?? []"
            :key="item.path"
            :aria-current="item.path === highlightedPath ? 'true' : undefined"
          >
            <td>
              <input
                v-if="item.capabilities.archive"
                :aria-label="t('fileManager.selectItem', { name: item.name })"
                :checked="isSelected(item)"
                class="form-check-input"
                type="checkbox"
                @change="toggleSelection(item, $event)"
              >
            </td>
            <td>
              <a
                v-if="item.capabilities.list || item.capabilities.read"
                class="text-decoration-none"
                href="#"
                @click.prevent="openItem(item)"
              >
                <i v-if="item.kind === 'directory'" class="bi bi-folder" aria-hidden="true" />
                <i v-else class="bi bi-file-earmark" aria-hidden="true" />
                <strong v-if="item.path === highlightedPath">{{ item.name }}</strong>
                <span v-else>{{ item.name }}</span>
              </a>
              <span v-else>{{ item.name }}</span>
            </td>
            <td>{{ t(`fileManager.kinds.${item.kind}`) }}</td>
            <td>{{ formatSize(item.size) }}</td>
            <td>{{ formatTime(item.modified_at) }}</td>
            <td>
              <div class="d-flex justify-content-end gap-1">
                <LteButton
                  v-if="item.capabilities.download"
                  class="icon-action-button"
                  :aria-label="t('fileManager.download')"
                  :title="t('fileManager.download')"
                  size="sm"
                  type="button"
                  @click="download(item)"
                >
                  <i class="bi bi-download" aria-hidden="true" />
                </LteButton>
                <LteButton
                  v-if="item.capabilities.rename"
                  class="icon-action-button"
                  :aria-label="t('fileManager.rename')"
                  :title="t('fileManager.rename')"
                  size="sm"
                  type="button"
                  @click="startRename(item)"
                >
                  <i class="bi bi-pencil" aria-hidden="true" />
                </LteButton>
                <LteButton
                  v-if="item.capabilities.delete"
                  class="icon-action-button"
                  :aria-label="t('common.delete')"
                  :title="t('common.delete')"
                  size="sm"
                  type="button"
                  @click="removeItem(item)"
                >
                  <i class="bi bi-trash" aria-hidden="true" />
                </LteButton>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <form v-if="createOpen" class="d-flex flex-wrap align-items-end gap-2 mb-3" @submit.prevent="createEntry">
      <div class="col">
        <label class="form-label" for="file-workspace-create-name">
          {{ createKind === 'directory' ? t('fileManager.createFolder') : t('fileManager.createFile') }}
        </label>
        <input id="file-workspace-create-name" v-model="createName" class="form-control" type="text">
      </div>
      <div class="d-flex gap-2">
        <LteButton class="action-button" type="button" @click="createOpen = false"><i class="bi bi-x-lg" aria-hidden="true" />{{ t('common.cancel') }}</LteButton>
        <LteButton class="action-button" :disabled="!createName.trim() || createSaving" type="submit">
          <span v-if="createSaving" class="spinner-border spinner-border-sm" aria-hidden="true" />
          <i v-else class="bi bi-floppy" aria-hidden="true" />
          {{ t('common.save') }}
        </LteButton>
      </div>
    </form>

    <form v-if="renameOpen" class="d-flex flex-wrap align-items-end gap-2 mb-3" @submit.prevent="renameItem">
      <div class="col">
        <label class="form-label" for="file-workspace-rename-name">
          {{ t('fileManager.rename') }}: {{ renamingItem?.name }}
        </label>
        <input id="file-workspace-rename-name" v-model="renameName" class="form-control" type="text">
      </div>
      <div class="d-flex gap-2">
        <LteButton class="action-button" type="button" @click="renameOpen = false"><i class="bi bi-x-lg" aria-hidden="true" />{{ t('common.cancel') }}</LteButton>
        <LteButton class="action-button" :disabled="!renameName.trim() || renameSaving" type="submit">
          <span v-if="renameSaving" class="spinner-border spinner-border-sm" aria-hidden="true" />
          <i v-else class="bi bi-floppy" aria-hidden="true" />
          {{ t('common.save') }}
        </LteButton>
      </div>
    </form>
  </section>
</template>
