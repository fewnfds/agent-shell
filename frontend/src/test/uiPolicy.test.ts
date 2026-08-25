import { spawnSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

const checkerPath = join(process.cwd(), 'scripts', 'check-ui-policy.mjs')
const temporaryRoots: string[] = []

const basePolicy = {
  version: 2,
  dependencies: {
    requiredExact: { '@adminlte/vue': '0.3.0', vue: '3.5.40' },
    forbidden: ['@adminlte/vue/plugins', 'element-plus'],
  },
  adminLteVue: {
    cssImportPaths: ['src/main.ts'],
    controlledImports: { LteModal: ['src/components/ModalHost.vue'] },
  },
  icons: { cssImportPaths: ['src/main.ts'] },
  styles: {
    globalCssPaths: ['src/styles/management-console.css'],
    allowScopedSfcStyles: true,
    inlineStylePaths: [],
    hardcodedColorsAllowed: false,
  },
}

function write(root: string, file: string, content: string): void {
  const target = join(root, file)
  mkdirSync(dirname(target), { recursive: true })
  writeFileSync(target, content, 'utf8')
}

function runFixture(files: Record<string, string>) {
  const root = mkdtempSync(join(tmpdir(), 'agent-shell-ui-policy-'))
  temporaryRoots.push(root)
  write(root, 'package.json', JSON.stringify({
    name: 'ui-policy-fixture',
    private: true,
    type: 'module',
    dependencies: { '@adminlte/vue': '0.3.0', vue: '3.5.40' },
  }))
  write(root, 'ui-policy.json', JSON.stringify(basePolicy))
  write(root, 'src/main.ts', `
    import '@adminlte/vue/css'
    import 'bootstrap-icons/font/bootstrap-icons.css'
    import './styles/management-console.css'
  `)
  write(root, 'src/styles/management-console.css', '')
  for (const [file, content] of Object.entries(files)) write(root, file, content)
  return spawnSync(process.execPath, [checkerPath, '--root', root], { encoding: 'utf8' })
}

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) rmSync(root, { force: true, recursive: true })
})

describe('ui-policy checker', () => {
  it('allows ordinary Vue composition, Bootstrap classes/icons and scoped component styles', () => {
    const result = runFixture({
      'src/components/FancyButton.vue': `
        <script setup lang="ts">
        import { LteButton } from '@adminlte/vue'
        const classes = ['btn', 'btn-primary']
        </script>
        <template><LteButton :class="classes"><i class="bi bi-stars" />OK</LteButton></template>
        <style scoped>.local-layout { color: var(--bs-body-color); }</style>
      `,
    })

    expect(result.status, result.stderr).toBe(0)
    expect(result.stdout).toContain('UI policy check passed')
  })

  it('rejects a forbidden second UI or plugin import', () => {
    const result = runFixture({
      'src/pages/ExamplePage.vue': `
        <script setup lang="ts">
        import { LteInputFlatpickr } from '@adminlte/vue/plugins'
        </script>
        <template><div /></template>
      `,
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('importing forbidden dependency "@adminlte/vue/plugins"')
  })

  it('rejects default AdminLTE registration and shell primitives outside their owner', () => {
    const result = runFixture({
      'src/pages/ExamplePage.vue': `
        <script setup lang="ts">
        import AdminLteVue, { LteModal } from '@adminlte/vue'
        void AdminLteVue
        </script>
        <template><LteModal /></template>
      `,
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('AdminLTE must use named imports')
    expect(result.stderr).toContain('AdminLTE shell primitive "LteModal" is owned by')
  })

  it('rejects framework CSS imports outside the shared entry owner', () => {
    const result = runFixture({
      'src/pages/example.ts': `
        import '@adminlte/vue/css'
        import 'bootstrap-icons/font/bootstrap-icons.css'
      `,
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('@adminlte/vue/css may only be imported by the shared CSS entry owner')
    expect(result.stderr).toContain('Bootstrap Icons CSS may only be imported by the shared CSS entry owner')
  })

  it('rejects a shared entry that drops a required framework stylesheet', () => {
    const result = runFixture({
      'src/main.ts': `import '@adminlte/vue/css'`,
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('must import required shared stylesheet "bootstrap-icons/font/bootstrap-icons.css"')
    expect(result.stderr).toContain('shared project stylesheet must be imported by a source entry')
  })

  it('rejects inline style, global SFC style and hardcoded theme colors', () => {
    const result = runFixture({
      'src/pages/ExamplePage.vue': `
        <template><div style="display: block" /></template>
        <style>.example { color: #fff; }</style>
      `,
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('inline styles are forbidden')
    expect(result.stderr).toContain('SFC styles must be scoped')
    expect(result.stderr).toContain('hardcoded colors are forbidden')
  })

  it('rejects additional global CSS files', () => {
    const result = runFixture({
      'src/styles/feature.css': '.feature { color: var(--bs-body-color); }',
    })

    expect(result.status).toBe(1)
    expect(result.stderr).toContain('global project CSS must use the shared policy-owned entry')
  })
})
