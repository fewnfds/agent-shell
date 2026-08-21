<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const props = withDefaults(defineProps<{
  page: number
  pageSize: number
  itemCount: number
  ariaLabel: string
  id: string
  total: number
  totalPages: number
  pageSizeOptions?: number[]
}>(), {
  pageSizeOptions: () => [20, 50, 100],
})

const emit = defineEmits<{
  change: [page: number]
  pageSizeChange: [pageSize: number]
}>()

const { t } = useI18n()
const jumpTarget = ref(props.page)

const boundedTotalPages = computed(() => Math.max(1, props.totalPages))
const visiblePages = computed(() => {
  const center = Math.min(Math.max(props.page, 1), boundedTotalPages.value)
  const start = Math.max(1, center - 3)
  const end = Math.min(boundedTotalPages.value, center + 3)
  return Array.from({ length: end - start + 1 }, (_, index) => start + index)
})
const firstResult = computed(() => props.total === 0 ? 0 : ((props.page - 1) * props.pageSize) + 1)
const lastResult = computed(() => props.total === 0
  ? 0
  : Math.min(props.total, firstResult.value + props.itemCount - 1))

const summary = computed(() => t('common.pagination.numberedSummary', {
  start: firstResult.value,
  end: lastResult.value,
  total: props.total,
  page: props.page,
  totalPages: boundedTotalPages.value,
}))

watch(() => props.page, (value) => {
  jumpTarget.value = value
})

function canChange(page: number): boolean {
  if (page < 1 || page === props.page) return false
  return page <= boundedTotalPages.value
}

function change(page: number): void {
  if (canChange(page)) emit('change', page)
}

function changePageSize(event: Event): void {
  const value = Number((event.target as HTMLSelectElement).value)
  if (!Number.isInteger(value) || value <= 0 || value === props.pageSize) return
  emit('pageSizeChange', value)
}

function jump(): void {
  const target = Math.trunc(Number(jumpTarget.value))
  if (!Number.isFinite(target)) return
  if (target === props.page) {
    jumpTarget.value = props.page
    return
  }
  change(target)
}
</script>

<template>
  <nav class="collection-pager" :aria-label="ariaLabel">
    <p class="text-body-secondary small mb-0" aria-live="polite">
      {{ summary }}
    </p>

    <div class="collection-pager-controls">
      <div class="collection-page-size">
        <label class="form-label mb-0" :for="`${id}-page-size`">
          {{ t('common.pagination.pageSize') }}
        </label>
        <select
          :id="`${id}-page-size`"
          class="form-select form-select-sm"
          :value="pageSize"
          @change="changePageSize"
        >
          <option v-for="option in pageSizeOptions" :key="option" :value="option">
            {{ t('common.pagination.pageSizeOption', { count: option }) }}
          </option>
        </select>
      </div>

      <ul class="pagination flex-wrap mb-0">
        <li class="page-item">
          <button class="page-link" :disabled="page <= 1" type="button" @click="change(1)">
            {{ t('common.pagination.first') }}
          </button>
        </li>
        <li class="page-item">
          <button class="page-link" :disabled="page <= 1" type="button" @click="change(page - 1)">
            {{ t('common.previousPage') }}
          </button>
        </li>

        <template v-for="pageNumber in visiblePages" :key="pageNumber">
          <li v-if="pageNumber === page" class="page-item active" aria-current="page">
            <span class="page-link">{{ pageNumber }}</span>
          </li>
          <li v-else class="page-item">
            <button
              class="page-link"
              type="button"
              :aria-label="t('common.pagination.pageLabel', { page: pageNumber })"
              @click="change(pageNumber)"
            >
              {{ pageNumber }}
            </button>
          </li>
        </template>

        <li class="page-item">
          <button
            class="page-link"
            :disabled="page >= boundedTotalPages"
            type="button"
            @click="change(page + 1)"
          >
            {{ t('common.nextPage') }}
          </button>
        </li>
        <li class="page-item">
          <button
            class="page-link"
            :disabled="page >= boundedTotalPages"
            type="button"
            @click="change(boundedTotalPages)"
          >
            {{ t('common.pagination.last') }}
          </button>
        </li>
      </ul>

      <form class="collection-page-jump" @submit.prevent="jump">
        <label class="form-label mb-0" :for="`${id}-page-jump`">
          {{ t('common.pagination.jump') }}
        </label>
        <div class="input-group">
          <input
            :id="`${id}-page-jump`"
            v-model.number="jumpTarget"
            class="form-control"
            :max="boundedTotalPages"
            min="1"
            step="1"
            type="number"
          >
          <button class="btn btn-info" type="submit">{{ t('common.pagination.jumpAction') }}</button>
        </div>
      </form>
    </div>
  </nav>
</template>
