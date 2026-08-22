<script setup lang="ts">
import { LteButton } from '@adminlte/vue'
import { useI18n } from 'vue-i18n'

import ConfigurationBundleImport from '@/components/ConfigurationBundleImport.vue'
import type { ConfigLibraryApi } from '@/pages/configLibrary'

defineProps<{
  refreshing: boolean
  api?: Pick<ConfigLibraryApi, 'previewConfigurationBundle' | 'importConfigurationBundle'>
}>()
const emit = defineEmits<{ refresh: []; imported: [] }>()
const { t } = useI18n()
</script>

<template>
  <ConfigurationBundleImport :api="api" @imported="emit('imported')" />
  <LteButton class="action-button" :disabled="refreshing" theme="info" type="button" @click="emit('refresh')">
    <span v-if="refreshing" class="spinner-border spinner-border-sm" aria-hidden="true" />
    <i v-else class="bi bi-arrow-clockwise" aria-hidden="true" />
    {{ refreshing ? t('common.refreshing') : t('common.refresh') }}
  </LteButton>
</template>
