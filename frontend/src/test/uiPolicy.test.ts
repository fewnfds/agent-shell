import { spawnSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

const checkerPath = join(process.cwd(), 'scripts', 'check-ui-policy.mjs')
const temporaryRoots: string[] = []

const basePolicy = {
  version: 1,
  dependencies: {
    requiredExact: {
      '@adminlte/vue': '0.3.0',
      vue: '3.5.40',
    },
    approvedRuntime: ['@adminlte/vue', 'vue'],
    forbidden: ['@adminlte/vue/plugins', 'overlayscrollbars'],
  },
  adminLteVue: {
    registration: 'named-imports-only',
    cssImportPaths: ['src/main.ts'],
    allowedImports: ['LteButton'],
    controlledImports: {
      LteModal: ['src/components/ModalHost.vue'],
    },
    allowedTypeImports: [],
    forbiddenImports: ['LteDashboardLayout', 'LteInputFlatpickr'],
    staticPropValues: {
      LteButton: { theme: ['primary', 'secondary', 'danger'] },
    },
    forbiddenProps: {
      LteButton: ['outline'],
    },
  },
  styles: {
    allowedProjectCss: ['src/styles/management-console.css'],
    allowedSfcStyleBlocks: [],
    allowedInlineStylePaths: [],
    hardcodedColorsAllowed: false,
    controlSemantics: {
      visibleLabelClass: 'form-label',
      hiddenLabelClass: 'visually-hidden',
      controlRowAttribute: 'data-ui-control-row',
      controlColumnPrefixes: ['col-'],
      peerLegendClasses: ['collection-filter-legend'],
    },
    classRecipes: [
      {
        name: 'fixture',
        paths: ['src/pages/*.vue'],
        classes: [
          'approved', 'col-md-6', 'collection-filter-legend', 'form-check', 'form-check-input',
          'form-label', 'form-switch', 'row', 'visually-hidden',
        ],
      },
    ],
  },
  layoutRules: {
    forbidAdjacentRows: true,
  },
  icons: {
    cssImportPaths: ['src/main.ts'],
    allowed: ['check-lg'],
    dynamicAllowedPaths: [],
  },
  localComponents: { approved: [] },
  testing: { adminLteIntegrationPaths: [] },
  migration: {
    temporaryRuntimeDependencies: [],
    legacyVuePaths: [],
    legacyElementImportPaths: [],
    legacyCssPaths: [],
  },
}

function write(root: string, file: string, content: string): void {
  const target = join(root, file)
  mkdirSync(dirname(target), { recursive: true })
  writeFileSync(target, content, 'utf8')
}

function createFixture(files: Record<string, string>): string {
  const root = mkdtempSync(join(tmpdir(), 'agent-shell-ui-policy-'))
  temporaryRoots.push(root)
  write(root, 'package.json', JSON.stringify({
    name: 'ui-policy-fixture',
    private: true,
    type: 'module',
    dependencies: {
      '@adminlte/vue': '0.3.0',
      vue: '3.5.40',
    },
  }))
  write(root, 'ui-policy.json', JSON.stringify(basePolicy))
  for (const [file, content] of Object.entries(files)) write(root, file, content)
  return root
}

function runFixture(files: Record<string, string>) {
  const root = createFixture(files)
  return spawnSync(process.execPath, [checkerPath, '--root', root], {
    encoding: 'utf8',
  })
}

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) rmSync(root, { force: true, recursive: true })
})

describe('ui-policy checker', () => {
  it('accepts a named approved component, variant, class and icon', () => {
    const result = runFixture({
      'src/pages/ExamplePage.vue': `
        <script setup lang="ts">
        import { LteButton } from '@adminlte/vue'
        </script>
        <template>
          <div class="approved">
            <i class="bi bi-check-lg" />
            <LteButton theme="primary" label="OK" />
          </div>
        </template>
      `,
    })

    expect(result.status, result.stderr).toBe(0)
    expect(result.stdout).toContain('UI policy check passed')
  })

  it('rejects Element Plus in a new file', () => {
    const result = runFixture({
      'src/pages/ExamplePage.vue': '<template><ElButton>Old</ElButton></template>',
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('Element Plus component <ElButton> is forbidden')
  })

  it('rejects the AdminLTE plugins entry', () => {
    const result = runFixture({
      'src/pages/ExamplePage.vue': `
        <script setup lang="ts">
        import { LteInputFlatpickr } from '@adminlte/vue/plugins'
        </script>
        <template><div /></template>
      `,
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('importing @adminlte/vue/plugins is forbidden')
  })

  it('rejects global AdminLTE registration imports', () => {
    const result = runFixture({
      'src/pages/ExamplePage.vue': `
        <script setup lang="ts">
        import AdminLteVue from '@adminlte/vue'
        void AdminLteVue
        </script>
        <template><div /></template>
      `,
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('default AdminLTE import/global registration is forbidden')
  })

  it('rejects page style blocks and inline styles', () => {
    const result = runFixture({
      'src/pages/ExamplePage.vue': `
        <template><div style="color: red" /></template>
        <style scoped>.example { color: red; }</style>
      `,
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('SFC <style> blocks are forbidden')
    expect(result.stderr).toContain('inline style attributes are forbidden')
  })

  it('rejects unknown classes and dynamic class bindings', () => {
    const result = runFixture({
      'src/pages/ExamplePage.vue': `
        <script setup lang="ts">const classes = 'approved'</script>
        <template><div class="mystery-card" :class="classes" /></template>
      `,
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('class "mystery-card" is outside approved recipes')
    expect(result.stderr).toContain('dynamic class bindings are forbidden')
  })

  it('rejects unknown Bootstrap icons', () => {
    const result = runFixture({
      'src/pages/ExamplePage.vue': '<template><i class="bi bi-skull" /></template>',
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('Bootstrap icon "bi-skull" is not approved')
  })

  it('rejects unapproved local UI components', () => {
    const result = runFixture({
      'src/components/FancyButton.vue': '<template><button type="button">Fancy</button></template>',
      'src/pages/ExamplePage.vue': `
        <script setup lang="ts">
        import FancyButton from '@/components/FancyButton.vue'
        </script>
        <template><FancyButton /></template>
      `,
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('local UI component is not approved in ui-policy.json')
  })

  it('rejects a peer control legend with a different visual label style', () => {
    const result = runFixture({
      'src/pages/ExamplePage.vue': `
        <template>
          <fieldset>
            <legend class="collection-filter-legend">Operations</legend>
          </fieldset>
        </template>
      `,
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('peer control legend must use Bootstrap .form-label')
  })

  it('rejects an unlabelled switch column beside a labelled input', () => {
    const result = runFixture({
      'src/pages/ExamplePage.vue': `
        <template>
          <div class="row" data-ui-control-row>
            <div class="col-md-6"><label class="form-label">Name</label><input></div>
            <div class="col-md-6">
              <div class="form-check form-switch">
                <input class="form-check-input" type="checkbox">
                <label class="visually-hidden">Enabled</label>
              </div>
            </div>
          </div>
        </template>
      `,
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('switch column beside labelled controls must include .form-label')
  })

  it('rejects adjacent Bootstrap rows', () => {
    const result = runFixture({
      'src/pages/ExamplePage.vue': `
        <template>
          <div>
            <div class="row"><div class="col-md-6" /></div>
            <div class="row"><div class="col-md-6" /></div>
          </div>
        </template>
      `,
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('adjacent Bootstrap .row elements are forbidden')
  })

  it('does not treat a repeated list row as a labelled form-control row', () => {
    const result = runFixture({
      'src/pages/ExamplePage.vue': `
        <template>
          <ul>
            <li>
              <div class="row">
                <div class="col-md-6"><label class="form-label">Name</label><input></div>
                <div class="col-md-6">
                  <div class="form-check form-switch">
                    <input class="form-check-input" type="checkbox">
                    <label class="visually-hidden">Enabled</label>
                  </div>
                </div>
              </div>
            </li>
          </ul>
        </template>
      `,
    })

    expect(result.status).toBe(0)
  })
})
