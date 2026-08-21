<script setup lang="ts">
/* eslint-disable vue/no-bare-strings-in-template -- Fixed technical strings are visual test fixtures. */
import { LteAlert, LteButton, LteCard, LteProgress } from '@adminlte/vue'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import FormField from '@/components/FormField.vue'
import PageShell from '@/components/PageShell.vue'
import '@/styles/style-lab.css'

const { t } = useI18n()
const palette = ref(1)
const demoSwitch = ref(true)
const demoCheck = ref(true)
const demoName = ref('local-model')
const demoProvider = ref('openai')
const demoInterval = ref(1000)
const demoDescription = ref(t('styleLab.samples.descriptionValue'))
const paletteLabel = computed(() => t(`styleLab.palettes.${palette.value}`))

function remix(): void {
  const choices = [1, 2, 3].filter((value) => value !== palette.value)
  palette.value = choices[Math.floor(Math.random() * choices.length)] ?? 1
  demoSwitch.value = Math.random() >= 0.35
}
</script>

<template>
  <PageShell>
    <template #actions>
      <LteButton theme="info" type="button" @click="remix">
        <i class="bi bi-arrow-clockwise me-2" aria-hidden="true" />
        {{ t('styleLab.remix') }} {{ paletteLabel }}
      </LteButton>
    </template>

    <div class="style-lab" :data-palette="palette">
      <section class="lab-intro">
        <div>
          <span class="lab-kicker">{{ t('styleLab.marker') }}</span>
          <h2>{{ t('styleLab.heading') }}</h2>
          <p>{{ t('styleLab.description') }}</p>
        </div>
        <div class="lab-control-sample">
          <span class="lab-control-label">{{ t('styleLab.switchBaseline') }}</span>
          <div class="form-check form-switch">
            <input
              id="style-lab-switch"
              v-model="demoSwitch"
              class="form-check-input"
              role="switch"
              type="checkbox"
            >
            <label class="form-check-label" for="style-lab-switch">
              {{ demoSwitch ? t('common.enabled') : t('common.disabled') }}
            </label>
          </div>
        </div>
      </section>

      <section class="lab-section">
        <header class="lab-section__header">
          <span class="lab-section__index">01</span>
          <h2>{{ t('styleLab.sections.buttons') }}</h2>
        </header>
        <div class="lab-surface">
          <div class="lab-cluster">
            <LteButton theme="primary" type="button">{{ t('styleLab.samples.primary') }}</LteButton>
            <LteButton theme="secondary" type="button">{{ t('styleLab.samples.secondary') }}</LteButton>
            <LteButton theme="success" type="button">{{ t('styleLab.samples.success') }}</LteButton>
            <LteButton theme="warning" type="button">{{ t('styleLab.samples.warning') }}</LteButton>
            <LteButton theme="danger" type="button">{{ t('styleLab.samples.danger') }}</LteButton>
            <LteButton theme="info" type="button">{{ t('styleLab.samples.info') }}</LteButton>
            <LteButton disabled theme="secondary" type="button">{{ t('styleLab.samples.disabled') }}</LteButton>
          </div>
          <div class="lab-cluster">
            <LteButton size="sm" theme="primary" type="button">
              <i class="bi bi-plus-lg me-2" aria-hidden="true" />
              {{ t('styleLab.samples.compact') }}
            </LteButton>
            <LteButton size="lg" theme="primary" type="button">{{ t('styleLab.samples.large') }}</LteButton>
            <button class="btn btn-outline-primary" type="button">{{ t('styleLab.samples.secondary') }}</button>
          </div>
          <div class="lab-cluster" role="group" :aria-label="t('styleLab.samples.actions')">
            <button class="btn btn-secondary btn-sm" type="button" :title="t('styleLab.samples.add')" :aria-label="t('styleLab.samples.add')">
              <i class="bi bi-plus-lg" aria-hidden="true" />
            </button>
            <button class="btn btn-secondary btn-sm" type="button" :title="t('styleLab.samples.refresh')" :aria-label="t('styleLab.samples.refresh')">
              <i class="bi bi-arrow-clockwise" aria-hidden="true" />
            </button>
            <button class="btn btn-secondary btn-sm" type="button" :title="t('styleLab.samples.download')" :aria-label="t('styleLab.samples.download')">
              <i class="bi bi-download" aria-hidden="true" />
            </button>
            <button class="btn btn-danger btn-sm" type="button" :title="t('styleLab.samples.delete')" :aria-label="t('styleLab.samples.delete')">
              <i class="bi bi-trash" aria-hidden="true" />
            </button>
          </div>
        </div>
      </section>

      <section class="lab-section">
        <header class="lab-section__header">
          <span class="lab-section__index">02</span>
          <h2>{{ t('styleLab.sections.forms') }}</h2>
        </header>
        <form class="lab-surface lab-form-grid" @submit.prevent>
          <div>
            <label class="form-label" for="lab-configuration-name">{{ t('styleLab.samples.configurationName') }}</label>
            <input
              id="lab-configuration-name"
              v-model="demoName"
              autocomplete="off"
              class="form-control"
              :placeholder="t('styleLab.samples.configurationPlaceholder')"
            >
          </div>
          <div>
            <label class="form-label" for="lab-provider">{{ t('styleLab.samples.provider') }}</label>
            <select id="lab-provider" v-model="demoProvider" class="form-select">
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="custom">OpenAI-compatible</option>
            </select>
          </div>
          <FormField
            class="lab-form-span"
            control-id="lab-alert-interval"
            field-path="debounce_ms"
            label-key="systemSettings.validationDebounceMs"
          >
            <div class="input-group">
              <input
                id="lab-alert-interval"
                v-model.number="demoInterval"
                aria-describedby="lab-alert-interval-unit"
                class="form-control"
                min="100"
                step="100"
                type="number"
              >
              <span id="lab-alert-interval-unit" class="input-group-text">ms</span>
            </div>
          </FormField>
          <div>
            <label class="form-label" for="lab-description">{{ t('styleLab.samples.description') }}</label>
            <textarea id="lab-description" v-model="demoDescription" class="form-control" rows="4" />
          </div>
          <FormField
            control-id="lab-invalid"
            :error="t('styleLab.samples.invalid')"
            field-path="name"
            label-key="styleLab.samples.configurationName"
          >
            <template #default="{ describedBy }">
              <input
                id="lab-invalid"
                :aria-describedby="describedBy"
                aria-invalid="true"
                class="form-control is-invalid"
                required
                value=""
              >
            </template>
          </FormField>
          <div>
            <label class="form-label" for="lab-readonly">{{ t('styleLab.samples.readonly') }}</label>
            <input id="lab-readonly" class="form-control" readonly value="agent-shell">
          </div>
          <fieldset class="lab-choice-group">
            <legend class="visually-hidden">{{ t('styleLab.sections.forms') }}</legend>
            <div class="form-check form-switch">
              <input id="lab-stream" v-model="demoSwitch" class="form-check-input" role="switch" type="checkbox">
              <label class="form-check-label" for="lab-stream">{{ t('styleLab.samples.stream') }}</label>
            </div>
            <div class="form-check">
              <input id="lab-retain-logs" v-model="demoCheck" class="form-check-input" type="checkbox">
              <label class="form-check-label" for="lab-retain-logs">{{ t('styleLab.samples.retainLogs') }}</label>
            </div>
          </fieldset>
        </form>
      </section>

      <section class="lab-section">
        <header class="lab-section__header">
          <span class="lab-section__index">03</span>
          <h2>{{ t('styleLab.sections.cards') }}</h2>
        </header>
        <div class="lab-grid lab-grid--compact">
          <LteCard class="h-100" :title="t('styleLab.samples.defaultCard')">
            <p class="card-text text-body-secondary">{{ t('styleLab.samples.defaultCardDetail') }}</p>
          </LteCard>
          <article class="card card-primary h-100">
            <header class="card-header d-flex align-items-center gap-2">
              <h3 class="card-title">{{ t('styleLab.samples.actionCard') }}</h3>
              <button
                class="btn btn-secondary btn-sm ms-auto"
                type="button"
                :aria-label="t('common.edit')"
                :title="t('common.edit')"
              >
                <i class="bi bi-pencil" aria-hidden="true" />
              </button>
            </header>
            <div class="card-body">
              <p class="card-text text-body-secondary">{{ t('styleLab.samples.actionCardDetail') }}</p>
            </div>
          </article>
          <article class="card card-outline card-danger h-100">
            <header class="card-header">
              <h3 class="card-title">{{ t('styleLab.samples.alertCard') }}</h3>
            </header>
            <div class="card-body">
              <p class="card-text text-body-secondary">{{ t('styleLab.samples.alertCardDetail') }}</p>
            </div>
          </article>
        </div>
      </section>

      <section class="lab-section">
        <header class="lab-section__header">
          <span class="lab-section__index">04</span>
          <h2>{{ t('styleLab.sections.tables') }}</h2>
        </header>
        <div class="table-responsive lab-table-frame">
          <table class="table table-hover table-striped align-middle mb-0">
            <thead class="management-table-head">
              <tr>
                <th scope="col">{{ t('styleLab.samples.name') }}</th>
                <th scope="col">{{ t('styleLab.samples.type') }}</th>
                <th scope="col">{{ t('styleLab.samples.status') }}</th>
                <th class="text-end" scope="col">{{ t('styleLab.samples.actions') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td class="fw-semibold">local-model</td>
                <td>{{ t('styleLab.samples.model') }}</td>
                <td><span class="badge text-bg-success">{{ t('styleLab.samples.ready') }}</span></td>
                <td class="text-end">
                  <button class="btn btn-secondary btn-sm" type="button" :aria-label="t('common.edit')" :title="t('common.edit')">
                    <i class="bi bi-pencil" aria-hidden="true" />
                  </button>
                </td>
              </tr>
              <tr>
                <td class="fw-semibold">release-notes</td>
                <td>{{ t('styleLab.samples.skill') }}</td>
                <td><span class="badge text-bg-warning">{{ t('styleLab.samples.draft') }}</span></td>
                <td class="text-end">
                  <button class="btn btn-secondary btn-sm" type="button" :aria-label="t('common.edit')" :title="t('common.edit')">
                    <i class="bi bi-pencil" aria-hidden="true" />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="lab-section">
        <header class="lab-section__header">
          <span class="lab-section__index">05</span>
          <h2>{{ t('styleLab.sections.feedback') }}</h2>
        </header>
        <div class="lab-feedback-grid">
          <LteAlert :title="t('styleLab.samples.successTitle')" theme="success">
            {{ t('styleLab.samples.successDetail') }}
          </LteAlert>
          <LteAlert :title="t('styleLab.samples.warningTitle')" theme="warning">
            {{ t('styleLab.samples.warningDetail') }}
          </LteAlert>
          <div class="lab-surface lab-form-span">
            <div class="d-flex justify-content-between mb-2">
              <span class="fw-semibold">{{ t('styleLab.samples.progress') }}</span>
              <span class="font-monospace">64%</span>
            </div>
            <LteProgress :value="64" show-label theme="primary" />
          </div>
        </div>
      </section>

      <section class="lab-section">
        <header class="lab-section__header">
          <span class="lab-section__index">06</span>
          <h2>{{ t('styleLab.sections.experiments') }}</h2>
        </header>
        <div class="lab-grid">
          <article class="card card-primary lab-sample">
            <header class="card-header">
              <h3 class="card-title">
                <i class="bi bi-gear me-2" aria-hidden="true" />
                A {{ t('styleLab.cards.adminHeader') }}
              </h3>
            </header>
            <div class="card-body">
              <p class="text-body-secondary">{{ t('styleLab.cards.adminHeaderDetail') }}</p>
              <label class="form-label" for="lab-a-input">Base URL</label>
              <input id="lab-a-input" class="form-control" readonly value="http://127.0.0.1:19100/v1">
            </div>
          </article>

          <article class="card card-outline card-info lab-sample">
            <header class="card-header">
              <h3 class="card-title">
                <i class="bi bi-info-circle me-2" aria-hidden="true" />
                B {{ t('styleLab.cards.adminOutline') }}
              </h3>
            </header>
            <div class="card-body">
              <p class="text-body-secondary">{{ t('styleLab.cards.adminOutlineDetail') }}</p>
              <div class="lab-actions">
                <span class="badge text-bg-info">API</span>
                <span class="badge text-bg-success">READY</span>
              </div>
            </div>
          </article>

          <article class="lab-card lab-card--rail">
            <header class="lab-card__header">
              <span class="lab-card__icon"><i class="bi bi-sliders" aria-hidden="true" /></span>
              <div>
                <span class="lab-card__eyebrow">CONTROL</span>
                <h3>C {{ t('styleLab.cards.rail') }}</h3>
              </div>
            </header>
            <div class="lab-card__body">
              <p>{{ t('styleLab.cards.railDetail') }}</p>
              <div class="lab-mini-field">
                <span>{{ t('eventFeed.retention.title') }}</span>
                <strong>ON</strong>
              </div>
            </div>
          </article>

          <article class="lab-card lab-card--aurora">
            <header class="lab-card__header">
              <span class="lab-card__eyebrow">AURORA PANEL</span>
              <span class="badge text-bg-primary">LIVE</span>
            </header>
            <div class="lab-card__body">
              <h3>D {{ t('styleLab.cards.aurora') }}</h3>
              <p>{{ t('styleLab.cards.auroraDetail') }}</p>
              <div class="lab-kpi-row">
                <strong>24</strong>
                <span>events / min</span>
              </div>
            </div>
          </article>

          <article class="lab-card lab-card--terminal">
            <header class="lab-card__header">
              <div class="lab-terminal-dots" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
              <span>runtime://diagnostics</span>
            </header>
            <div class="lab-card__body">
              <h3>E {{ t('styleLab.cards.terminal') }}</h3>
              <p class="lab-terminal-line"><span>$</span> agent-shell status --verbose</p>
              <p class="lab-terminal-line"><span>✓</span> API Server ready</p>
            </div>
          </article>

          <article class="lab-card lab-card--layered">
            <header class="lab-card__header">
              <span class="lab-card__index">F</span>
              <div>
                <span class="lab-card__eyebrow">STACKED HEADER</span>
                <h3>{{ t('styleLab.cards.layered') }}</h3>
              </div>
            </header>
            <div class="lab-card__body">
              <p>{{ t('styleLab.cards.layeredDetail') }}</p>
              <div class="lab-actions">
                <button class="btn btn-primary btn-sm" type="button">Save</button>
                <button class="btn btn-warning btn-sm" type="button">Reset</button>
              </div>
            </div>
          </article>

          <article class="lab-card lab-card--glass">
            <header class="lab-card__header">
              <i class="bi bi-circle-half" aria-hidden="true" />
              <span class="lab-card__eyebrow">TRANSLUCENT</span>
            </header>
            <div class="lab-card__body">
              <h3>G {{ t('styleLab.cards.glass') }}</h3>
              <p>{{ t('styleLab.cards.glassDetail') }}</p>
              <div class="lab-swatch-row" aria-hidden="true">
                <span class="lab-swatch" />
                <span class="lab-swatch" />
                <span class="lab-swatch" />
              </div>
            </div>
          </article>

          <article class="lab-card lab-card--dense">
            <header class="lab-card__header">
              <div>
                <span class="lab-card__eyebrow">DENSE DATA</span>
                <h3>H {{ t('styleLab.cards.dense') }}</h3>
              </div>
              <span class="lab-dot" aria-label="online" />
            </header>
            <div class="lab-card__body">
              <dl class="lab-definition-list">
                <div><dt>Host</dt><dd>127.0.0.1</dd></div>
                <div><dt>Port</dt><dd>19100</dd></div>
                <div><dt>Mode</dt><dd>Local</dd></div>
              </dl>
            </div>
          </article>

          <article class="lab-card lab-card--corner">
            <span class="lab-corner-mark"><i class="bi bi-check-lg" aria-hidden="true" /></span>
            <header class="lab-card__header">
              <span class="lab-card__eyebrow">STATUS CARD</span>
              <h3>I {{ t('styleLab.cards.corner') }}</h3>
            </header>
            <div class="lab-card__body">
              <strong class="lab-status-value">Healthy</strong>
              <p>{{ t('styleLab.cards.cornerDetail') }}</p>
            </div>
          </article>

          <article class="lab-card lab-card--split">
            <header class="lab-card__header">
              <span class="lab-card__icon"><i class="bi bi-boxes" aria-hidden="true" /></span>
              <div>
                <span class="lab-card__eyebrow">ACTION PANEL</span>
                <h3>J {{ t('styleLab.cards.split') }}</h3>
              </div>
            </header>
            <div class="lab-card__body">
              <p>{{ t('styleLab.cards.splitDetail') }}</p>
            </div>
            <footer class="lab-card__footer">
              <span>3 changes</span>
              <button class="btn btn-primary btn-sm" type="button">Apply</button>
            </footer>
          </article>
        </div>
      </section>
    </div>
  </PageShell>
</template>
