import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it } from 'vitest'

import { taskDispatcherAdapter } from '@/domain/blocks'
import { en } from '@/locales/en'

import TaskDispatcherEditor from './TaskDispatcherEditor.vue'

const i18n = () => createI18n({
  legacy: false,
  locale: 'en',
  messages: { en },
})

describe('TaskDispatcherEditor', () => {
  it('creates an editable package draft from the rainfall template', async () => {
    const templateKey = '内置示例-rainfall-task-dispatcher'
    const source = 'def create_dispatcher():\n    return dispatch\n'
    const wrapper = mount(TaskDispatcherEditor, {
      props: {
        modelValue: taskDispatcherAdapter.blank(),
        catalog: [{
          key: templateKey,
          format_version: 1,
          family: 'workflow-node',
          adapter: 'task-dispatcher',
          name: 'rainfall-task-dispatcher',
          revision: 'revision',
          files: [
            { path: 'main.py', content: source, exists: true },
            { path: 'requirements.txt', content: '', exists: true },
          ],
        }],
      },
      global: { plugins: [i18n()] },
    })

    await wrapper.get('select').setValue(templateKey)

    const emitted = wrapper.emitted('update:modelValue')?.at(-1)?.[0]
    expect(emitted).toMatchObject({
      python_package: { folder: '' },
      python_package_template: {
        key: templateKey,
        revision: 'revision',
      },
    })
  })
})
