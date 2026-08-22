<script setup lang="ts">
const props = withDefaults(defineProps<{
  loading?: boolean
  layoutTestId?: string
  asideTestId?: string
}>(), {
  loading: false,
  layoutTestId: undefined,
  asideTestId: undefined,
})
</script>

<template>
  <div
    class="row g-3 align-items-start configuration-loading-surface"
    :aria-busy="props.loading"
    :data-loading="props.loading"
    :data-testid="props.layoutTestId"
    :inert="props.loading || undefined"
  >
    <section class="col-lg-9">
      <slot name="editor" />
    </section>
    <aside
      class="col-lg-3 validation-sidebar"
      :data-testid="props.asideTestId"
    >
      <slot name="aside" />
    </aside>
  </div>
</template>
