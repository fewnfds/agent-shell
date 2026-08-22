<script setup lang="ts">
import { LteButton } from '@adminlte/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = withDefaults(defineProps<{
  hasSelection?: boolean
  canSave?: boolean
  loading?: boolean
  saving?: boolean
  copying?: boolean
  deleting?: boolean
  showEdit?: boolean
}>(), {
  hasSelection: false,
  canSave: true,
  loading: false,
  saving: false,
  copying: false,
  deleting: false,
  showEdit: false,
})

const emit = defineEmits<{
  copy: []
  delete: []
  new: []
  save: []
  edit: []
}>()

const { t } = useI18n()
const busy = computed(() => props.loading || props.saving || props.copying || props.deleting)
</script>

<template>
  <LteButton
    class="action-button"
    :disabled="!props.hasSelection || busy"
    theme="secondary"
    type="button"
    @click="emit('copy')"
  >
    <i class="bi bi-copy" aria-hidden="true" />
    {{ t('common.copy') }}
  </LteButton>
  <LteButton
    class="action-button"
    :disabled="!props.hasSelection || busy"
    theme="danger"
    type="button"
    @click="emit('delete')"
  >
    <i class="bi bi-trash" aria-hidden="true" />
    {{ props.deleting ? t('common.deleting') : t('common.delete') }}
  </LteButton>
  <LteButton
    class="action-button"
    :disabled="busy"
    theme="success"
    type="button"
    @click="emit('new')"
  >
    <i class="bi bi-plus-lg" aria-hidden="true" />
    {{ t('common.new') }}
  </LteButton>
  <LteButton
    class="action-button"
    :disabled="!props.canSave || busy"
    theme="primary"
    type="button"
    @click="emit('save')"
  >
    <span v-if="props.saving" class="spinner-border spinner-border-sm" aria-hidden="true" />
    <i v-else class="bi bi-floppy" aria-hidden="true" />
    {{ t('common.save') }}
  </LteButton>
  <LteButton
    v-if="props.showEdit"
    class="action-button"
    :disabled="!props.hasSelection || busy"
    theme="info"
    type="button"
    @click="emit('edit')"
  >
    <i class="bi bi-pencil" aria-hidden="true" />
    {{ t('common.edit') }}
  </LteButton>
  <slot />
</template>

