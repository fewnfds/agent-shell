<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import FileWorkspaceBrowser from '@/components/FileWorkspaceBrowser.vue'
import ModalHost from '@/components/ModalHost.vue'
import TextFileEditorSurface from '@/components/TextFileEditorSurface.vue'

const props = withDefaults(defineProps<{
  open: boolean
  path: string
  targetKind?: 'file' | 'directory'
  openEditorOnOpen?: boolean
}>(), {
  targetKind: 'file',
  openEditorOnOpen: false,
})
const emit = defineEmits<{
  close: []
  changed: []
}>()

const { t } = useI18n()
const editorPath = ref('')
const browserKey = ref(0)

const initialDirectory = computed(() => {
  if (props.targetKind === 'directory') return props.path
  const parts = props.path.split('/')
  return parts.length > 1 ? parts.slice(0, -1).join('/') : 'data'
})

function openFile(path: string): void {
  editorPath.value = path
}

function backToBrowser(): void {
  editorPath.value = ''
  browserKey.value += 1
}

function changed(): void {
  emit('changed')
}

watch(
  () => [props.open, props.path, props.openEditorOnOpen, props.targetKind] as const,
  ([open, path, openEditor]) => {
    if (!open) return
    editorPath.value = openEditor && props.targetKind === 'file' ? path : ''
    browserKey.value += 1
  },
  { immediate: true },
)
</script>

<template>
  <ModalHost
    :open="open"
    size="wide"
    :title="t('fileManager.title')"
    @close="emit('close')"
  >
    <TextFileEditorSurface
      v-if="editorPath"
      :path="editorPath"
      @back="backToBrowser"
      @saved="changed"
    />
    <FileWorkspaceBrowser
      v-else
      :key="browserKey"
      :highlighted-path="path"
      :initial-path="initialDirectory"
      @changed="changed"
      @open-file="openFile"
    />
  </ModalHost>
</template>
