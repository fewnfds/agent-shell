<script setup lang="ts">
import { ref } from 'vue'

import FileWorkspaceBrowser from '@/components/FileWorkspaceBrowser.vue'
import FileWorkspaceDialog from '@/components/FileWorkspaceDialog.vue'
import PageShell from '@/components/PageShell.vue'

const editorOpen = ref(false)
const editorPath = ref('')
const browser = ref<InstanceType<typeof FileWorkspaceBrowser> | null>(null)

function openFile(path: string): void {
  editorPath.value = path
  editorOpen.value = true
}

function refresh(): void {
  void browser.value?.refresh()
}
</script>

<template>
  <PageShell>
    <FileWorkspaceBrowser ref="browser" initial-path="data" @open-file="openFile" />
    <FileWorkspaceDialog
      :open="editorOpen"
      open-editor-on-open
      :path="editorPath"
      @changed="refresh"
      @close="editorOpen = false"
    />
  </PageShell>
</template>
