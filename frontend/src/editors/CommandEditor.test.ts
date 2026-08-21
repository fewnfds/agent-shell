import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'

import { commandAdapter } from '@/domain/blocks'
import { applyPythonPackageInspection } from '@/domain/blocks/pythonPackage'
import { en } from '@/locales/en'

import CommandEditor from './CommandEditor.vue'

const i18n = () => createI18n({
  legacy: false,
  locale: 'en',
  messages: { en },
})

const template = {
  key: 'threshold-router',
  format_version: 1 as const,
  family: 'workflow-node' as const,
  adapter: 'command' as const,
  name: 'threshold-router',
  revision: 'template-revision',
  files: [
    { path: 'main.py', content: 'def create_command():\n    return route\n', exists: true },
    { path: 'helpers/rules.py', content: 'THRESHOLD = 80\n', exists: true },
  ],
}

describe('CommandEditor', () => {
  it('selects a template by identity without rendering or emitting source content', async () => {
    const wrapper = mount(CommandEditor, {
      props: { modelValue: commandAdapter.blank(), catalog: [template] },
      global: { plugins: [i18n()] },
    })

    await wrapper.get('select').setValue(template.key)

    const emitted = wrapper.emitted('update:modelValue')?.at(-1)?.[0]
    expect(emitted).toMatchObject({
      python_package: { folder: '' },
      python_package_template: {
        key: template.key,
        revision: template.revision,
      },
    })
    expect(JSON.stringify(emitted)).not.toContain('create_command')
    expect(wrapper.find('textarea').exists()).toBe(false)
  })

  it('lists every projected private package path without loading file content', () => {
    const id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    const draft = commandAdapter.fromApi({
      id,
      name: 'Router',
      python_package: { folder: id },
    })
    applyPythonPackageInspection(draft, {
      repository_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      owner_id: id,
      revision: 'package-revision',
      files: [
        {
          path: 'helpers/rules.py',
          file_manager_path: `data/configuration-repositories/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/python_package_instances/command/${id}/helpers/rules.py`,
          size: 16,
          modified_at: '2026-08-21T00:00:00Z',
        },
        {
          path: 'package.json',
          file_manager_path: `data/configuration-repositories/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/python_package_instances/command/${id}/package.json`,
          size: 100,
          modified_at: '2026-08-21T00:00:00Z',
        },
      ],
      python_package_manifest: null,
      python_package_error: {
        message_key: 'resource.error.pythonPackage.idMismatch',
        message_args: {},
      },
      requirements_fingerprint: '',
      dependency_status: 'failed',
      dependency_error_code: 'resource.error.pythonPackage.idMismatch',
    })
    const wrapper = mount(CommandEditor, {
      props: { modelValue: draft },
      global: { plugins: [i18n()] },
    })

    expect(wrapper.text()).toContain('helpers/rules.py')
    expect(wrapper.text()).toContain('package.json')
    expect(wrapper.text()).toContain('The package.json id must match the folder name.')
    expect(wrapper.find('textarea').exists()).toBe(false)
  })

  it('does not offer a blank package template', () => {
    const wrapper = mount(CommandEditor, {
      props: { modelValue: commandAdapter.blank(), catalog: [] },
      global: { plugins: [i18n()] },
    })

    expect(wrapper.text()).not.toContain('Empty template')
    expect(wrapper.find('option[value="__empty__"]').exists()).toBe(false)
  })
})
