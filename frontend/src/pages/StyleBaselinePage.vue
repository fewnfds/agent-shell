<script setup lang="ts">
import { LteAccordion, LteAccordionItem, LteAlert, LteButton, LteCard, LteProgress } from '@adminlte/vue'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import FormField from '@/components/FormField.vue'
import PageShell from '@/components/PageShell.vue'
import { styleBaseline } from '@/generated/styleBaseline'

const { t } = useI18n()
const search = ref('')
const onlySuspect = ref(false)
const demoName = ref('local-model')
const demoDescription = ref('用于本地开发与样式核对。')
const demoSwitch = ref(true)

const filteredClasses = computed(() => {
  const query = search.value.trim().toLowerCase()
  return styleBaseline.classInventory.filter((item) => {
    if (onlySuspect.value && item.approved) return false
    if (!query) return true
    return [item.name, ...item.sources, ...item.recipes].some((value) => value.toLowerCase().includes(query))
  })
})

const suspectClasses = computed(() => styleBaseline.summary.suspectClassCount)
</script>

<template>
  <PageShell>
    <div class="style-baseline">
      <section class="mb-3" aria-labelledby="style-baseline-heading">
        <div class="d-flex flex-wrap align-items-start justify-content-between gap-3">
          <div>
            <span class="small text-uppercase text-body-secondary">{{ t('styleBaseline.marker') }}</span>
            <h2 id="style-baseline-heading" class="h4 mb-1">{{ t('styleBaseline.heading') }}</h2>
            <p class="text-body-secondary mb-0">{{ t('styleBaseline.description') }}</p>
          </div>
          <div class="text-end">
            <span class="badge text-bg-primary">{{ styleBaseline.summary.usedClassCount }} {{ t('styleBaseline.usedClasses') }}</span>
            <span class="badge text-bg-danger ms-2">{{ suspectClasses }} {{ t('styleBaseline.suspect') }}</span>
          </div>
        </div>
      </section>

      <section class="card card-outline mb-3" aria-labelledby="style-baseline-controls-heading">
        <header class="card-header">
          <h2 id="style-baseline-controls-heading" class="card-title">{{ t('styleBaseline.controls') }}</h2>
        </header>
        <div class="card-body">
          <div class="row g-3" data-ui-control-row>
            <div class="col-lg-8">
              <label class="form-label" for="style-baseline-search">{{ t('styleBaseline.search') }}</label>
              <input id="style-baseline-search" v-model="search" class="form-control" :placeholder="t('styleBaseline.searchPlaceholder')">
            </div>
            <div class="col-lg-4">
              <span class="form-label d-block">{{ t('styleBaseline.filter') }}</span>
              <div class="form-check form-switch">
                <input id="style-baseline-suspect-only" v-model="onlySuspect" class="form-check-input" role="switch" type="checkbox">
                <label class="form-check-label" for="style-baseline-suspect-only">{{ t('styleBaseline.onlySuspect') }}</label>
              </div>
            </div>
          </div>
          <p class="form-text mb-0 mt-2">{{ t('styleBaseline.generatedFrom') }}</p>
        </div>
      </section>

      <section class="mb-3" aria-labelledby="style-baseline-components-heading">
        <div class="d-flex align-items-center gap-2 mb-2">
          <h2 id="style-baseline-components-heading" class="h5 mb-0">{{ t('styleBaseline.components') }}</h2>
          <span class="badge text-bg-secondary">{{ styleBaseline.summary.componentCount }}</span>
        </div>
        <div class="row g-3">
          <div class="col-lg-6">
            <LteCard :title="t('styleBaseline.buttons')">
              <div class="d-flex flex-wrap gap-2">
                <LteButton class="action-button" theme="primary" type="button"><i class="bi bi-floppy" aria-hidden="true" />{{ t('common.save') }}</LteButton>
                <LteButton class="action-button" theme="secondary" type="button"><i class="bi bi-x-lg" aria-hidden="true" />{{ t('common.cancel') }}</LteButton>
                <LteButton class="action-button" theme="success" type="button"><i class="bi bi-check-lg" aria-hidden="true" />{{ t('common.confirm') }}</LteButton>
                <LteButton class="action-button" theme="warning" type="button"><i class="bi bi-arrow-clockwise" aria-hidden="true" />{{ t('common.retry') }}</LteButton>
                <LteButton class="action-button" theme="danger" type="button"><i class="bi bi-trash" aria-hidden="true" />{{ t('common.delete') }}</LteButton>
                <LteButton class="icon-action-button" :aria-label="t('common.new')" :title="t('common.new')" size="sm" theme="primary" type="button">
                  <i class="bi bi-plus-lg" aria-hidden="true" />
                </LteButton>
              </div>
              <div class="d-flex flex-wrap gap-2 mt-3">
                <button class="btn btn-outline-primary action-button" type="button"><i class="bi bi-eye" aria-hidden="true" />{{ t('styleBaseline.outline') }}</button>
                <button class="btn btn-secondary btn-sm icon-action-button" type="button" :aria-label="t('common.edit')" :title="t('common.edit')">
                  <i class="bi bi-pencil" aria-hidden="true" />
                </button>
                <button class="btn btn-danger btn-sm icon-action-button" type="button" :aria-label="t('common.delete')" :title="t('common.delete')">
                  <i class="bi bi-trash" aria-hidden="true" />
                </button>
              </div>
            </LteCard>
          </div>
          <div class="col-lg-6">
            <LteCard :title="t('styleBaseline.feedback')">
              <LteAlert class="mb-3" theme="success" :title="t('styleBaseline.success')">{{ t('styleBaseline.successDetail') }}</LteAlert>
              <LteAlert class="mb-3" theme="warning" :title="t('styleBaseline.warning')">{{ t('styleBaseline.warningDetail') }}</LteAlert>
              <div class="d-flex justify-content-between mb-2">
                <span class="fw-semibold">{{ t('styleBaseline.progress') }}</span>
                <span class="font-monospace">64%</span>
              </div>
              <LteProgress :value="64" show-label theme="primary" />
            </LteCard>
          </div>
        </div>
      </section>

      <section class="mb-3" aria-labelledby="style-baseline-forms-heading">
        <div class="d-flex align-items-center gap-2 mb-2">
          <h2 id="style-baseline-forms-heading" class="h5 mb-0">{{ t('styleBaseline.forms') }}</h2>
        </div>
        <div class="card">
          <div class="card-body">
            <div class="row g-3" data-ui-control-row>
              <div class="col-lg-6">
                <FormField control-id="style-baseline-name" field-path="name" :label-key="'styleBaseline.name'">
                  <input id="style-baseline-name" v-model="demoName" class="form-control">
                </FormField>
              </div>
              <div class="col-lg-6">
                <FormField control-id="style-baseline-provider" field-path="provider" :label-key="'styleBaseline.provider'">
                  <select id="style-baseline-provider" class="form-select">
                    <option>OpenAI</option>
                    <option>Anthropic</option>
                  </select>
                </FormField>
              </div>
              <div class="col-lg-6">
                <FormField control-id="style-baseline-description" field-path="description" :label-key="'styleBaseline.descriptionField'">
                  <textarea id="style-baseline-description" v-model="demoDescription" class="form-control" rows="3" />
                </FormField>
              </div>
              <div class="col-lg-6">
                <FormField control-id="style-baseline-invalid" field-path="name" :error="t('styleBaseline.invalid')" :label-key="'styleBaseline.invalidField'">
                  <input id="style-baseline-invalid" aria-invalid="true" class="form-control is-invalid" value="">
                </FormField>
                <div class="input-group">
                  <input class="form-control" type="number" value="1000" aria-label="Milliseconds">
                  <span class="input-group-text">ms</span>
                </div>
              </div>
            </div>
            <div class="d-flex flex-wrap align-items-center gap-3 mt-2">
              <div class="form-check form-switch">
                <input id="style-baseline-switch" v-model="demoSwitch" class="form-check-input" role="switch" type="checkbox">
                <label class="form-check-label" for="style-baseline-switch">{{ t('styleBaseline.switch') }}</label>
              </div>
              <div class="form-check">
                <input id="style-baseline-check" class="form-check-input" type="checkbox" checked>
                <label class="form-check-label" for="style-baseline-check">{{ t('styleBaseline.checkbox') }}</label>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="mb-3" aria-labelledby="style-baseline-content-heading">
        <div class="d-flex align-items-center gap-2 mb-2">
          <h2 id="style-baseline-content-heading" class="h5 mb-0">{{ t('styleBaseline.content') }}</h2>
        </div>
        <div class="row g-3">
          <div class="col-lg-8">
            <div class="table-responsive">
              <table class="table table-hover table-striped align-middle mb-0">
                <thead class="management-table-head">
                  <tr><th scope="col">{{ t('styleBaseline.name') }}</th><th scope="col">{{ t('styleBaseline.type') }}</th><th scope="col">{{ t('styleBaseline.status') }}</th></tr>
                </thead>
                <tbody>
                  <tr><td class="fw-semibold">local-model</td><td>Model</td><td><span class="badge text-bg-success">{{ t('styleBaseline.ready') }}</span></td></tr>
                  <tr><td class="fw-semibold">release-notes</td><td>Skill</td><td><span class="badge text-bg-warning">{{ t('styleBaseline.draft') }}</span></td></tr>
                </tbody>
              </table>
            </div>
          </div>
          <div class="col-lg-4">
            <div class="card card-outline card-primary h-100">
              <header class="card-header"><h3 class="card-title">{{ t('styleBaseline.accordion') }}</h3></header>
              <div class="card-body">
                <LteAccordion always-open flush>
                  <LteAccordionItem id="style-baseline-item-1" :title="t('styleBaseline.accordionFirst')">
                    <p class="mb-0 text-body-secondary">{{ t('styleBaseline.accordionDetail') }}</p>
                  </LteAccordionItem>
                  <LteAccordionItem id="style-baseline-item-2" :title="t('styleBaseline.accordionSecond')">
                    <p class="mb-0 text-body-secondary">{{ t('styleBaseline.accordionDetail') }}</p>
                  </LteAccordionItem>
                </LteAccordion>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="mb-3" aria-labelledby="style-baseline-inventory-heading">
        <div class="d-flex align-items-center gap-2 mb-2">
          <h2 id="style-baseline-inventory-heading" class="h5 mb-0">{{ t('styleBaseline.inventory') }}</h2>
          <span class="small text-body-secondary">{{ filteredClasses.length }} / {{ styleBaseline.summary.classCount }}</span>
        </div>
        <div class="table-responsive border rounded">
          <table class="table table-striped align-middle mb-0">
            <thead class="management-table-head">
              <tr>
                <th scope="col">{{ t('styleBaseline.className') }}</th>
                <th scope="col">{{ t('styleBaseline.usage') }}</th>
                <th scope="col">{{ t('styleBaseline.source') }}</th>
                <th scope="col">{{ t('styleBaseline.status') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in filteredClasses" :key="item.name">
                <td class="font-monospace text-break">{{ item.name }}</td>
                <td>{{ item.usageCount }}</td>
                <td class="small text-break">
                  <span v-for="source in item.sources" :key="source" class="d-block">{{ source }}</span>
                </td>
                <td>
                  <span v-if="item.status === 'registered'" class="badge text-bg-success">{{ t('styleBaseline.approved') }}</span>
                  <span v-else-if="item.status === 'external'" class="badge text-bg-secondary">{{ t('styleBaseline.external') }}</span>
                  <span v-else class="badge text-bg-danger">{{ t('styleBaseline.suspect') }}</span>
                </td>
              </tr>
              <tr v-if="filteredClasses.length === 0">
                <td class="text-body-secondary" colspan="4">{{ t('styleBaseline.noResults') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <LteAlert v-if="suspectClasses > 0" theme="danger" :title="t('styleBaseline.suspectTitle')">
        {{ t('styleBaseline.suspectDetail', { count: suspectClasses }) }}
      </LteAlert>
      <LteAlert v-else theme="success" :title="t('styleBaseline.cleanTitle')">
        {{ t('styleBaseline.cleanDetail') }}
      </LteAlert>
    </div>
  </PageShell>
</template>
