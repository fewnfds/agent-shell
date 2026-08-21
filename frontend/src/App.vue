<script setup lang="ts">
import AppShell from '@/components/AppShell.vue'
import AuthGate from '@/components/AuthGate.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ToastHost from '@/components/ToastHost.vue'
import { useConfirmation } from '@/composables/useConfirmation'
import { useToasts } from '@/composables/useToasts'
import { computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'

const { dismiss, items } = useToasts()
const { accept, cancel, current } = useConfirmation()
const route = useRoute()
const workflowLayout = computed(() => route.meta.layout === 'workflow')
</script>

<template>
  <RouterView v-if="workflowLayout" />
  <AppShell v-else />
  <AuthGate />
  <ToastHost
    :items="items"
    @dismiss="dismiss"
  />
  <ConfirmDialog
    :cancel-label="current?.cancelLabel ?? ''"
    :confirm-label="current?.confirmLabel ?? ''"
    :dangerous="current?.dangerous ?? false"
    :description="current?.description ?? ''"
    :open="current !== null"
    :title="current?.title ?? ''"
    @cancel="cancel"
    @confirm="accept"
  />
</template>
