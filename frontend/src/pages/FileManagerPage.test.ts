import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ManagementApiError,
  managementApi,
  type ManagedDirectory,
  type ManagedFileCapabilities,
} from '@/api'
import FileWorkspaceBrowser from '@/components/FileWorkspaceBrowser.vue'
import FileWorkspaceDialog from '@/components/FileWorkspaceDialog.vue'
import TextFileEditorSurface from '@/components/TextFileEditorSurface.vue'
import { useConfirmation } from '@/composables/useConfirmation'
import { en } from '@/locales/en'

const i18n = () => createI18n({
  legacy: false,
  locale: 'en',
  messages: { en },
})

const navigationCapabilities: ManagedFileCapabilities = {
  list: true,
  read: false,
  create: false,
  upload: false,
  write: false,
  download: false,
  archive: false,
  rename: false,
  delete: false,
}
const editableCapabilities: ManagedFileCapabilities = {
  list: true,
  read: true,
  create: true,
  upload: true,
  write: true,
  download: true,
  archive: true,
  rename: true,
  delete: true,
}

afterEach(() => {
  useConfirmation().cancel()
  vi.restoreAllMocks()
})

function browserApi(listManagedFiles: (path?: string) => Promise<ManagedDirectory>) {
  return {
    listManagedFiles: vi.fn(listManagedFiles),
    createManagedDirectory: vi.fn(),
    createManagedTextFile: vi.fn(),
    uploadManagedFile: vi.fn(),
    downloadManagedEntry: vi.fn(),
    previewManagedArchive: vi.fn(),
    downloadManagedArchive: vi.fn(),
    renameManagedEntry: vi.fn(),
    deleteManagedFile: vi.fn(),
  }
}

describe('File Workspace', () => {
  it('browses real data paths and enables commands only from backend capabilities', async () => {
    const root: ManagedDirectory = {
      path: 'data',
      capabilities: navigationCapabilities,
      items: [{
        name: 'files',
        path: 'data/files',
        kind: 'directory',
        size: null,
        modified_at: '2026-08-21T00:00:00Z',
        revision: 'root-revision',
        capabilities: { ...editableCapabilities, read: false, write: false },
      }],
    }
    const files: ManagedDirectory = {
      path: 'data/files',
      capabilities: editableCapabilities,
      items: [],
    }
    const api = browserApi(async (path = 'data') => path === 'data' ? root : files)
    const wrapper = mount(FileWorkspaceBrowser, {
      props: { api },
      global: { plugins: [i18n()] },
    })
    await flushPromises()

    expect(api.listManagedFiles).toHaveBeenCalledWith('data')
    expect(wrapper.text()).toContain('data')
    expect(wrapper.text()).toContain('files')
    expect(wrapper.text()).not.toContain('New folder')

    const filesLink = wrapper.findAll('a').find((link) => link.text().includes('files'))
    expect(filesLink?.classes()).toContain('text-decoration-none')
    expect(wrapper.get('tbody td:nth-child(2) a').exists()).toBe(true)
    expect(wrapper.find('tbody td:nth-child(2) button').exists()).toBe(false)
    await filesLink!.trigger('click')
    await flushPromises()

    expect(api.listManagedFiles).toHaveBeenLastCalledWith('data/files')
    expect(wrapper.text()).toContain('New folder')
    expect(wrapper.text()).toContain('Upload files')
  })

  it('opens a caller path at its real parent and waits for a file click before editing', async () => {
    const path = 'data/configuration-repositories/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/python_package_instances/command/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/main.py'
    const parent = path.slice(0, path.lastIndexOf('/'))
    const list = vi.spyOn(managementApi, 'listManagedFiles').mockResolvedValue({
      path: parent,
      capabilities: editableCapabilities,
      items: [{
        name: 'main.py',
        path,
        kind: 'file',
        size: 10,
        modified_at: '2026-08-21T00:00:00Z',
        revision: 'metadata-revision',
        capabilities: editableCapabilities,
      }],
    })
    const read = vi.spyOn(managementApi, 'readManagedTextFile').mockResolvedValue({
      path,
      content: 'SOURCE\n',
      revision: 'content-revision',
      capabilities: editableCapabilities,
    })
    const wrapper = mount(FileWorkspaceDialog, {
      props: { open: true, path },
      global: { plugins: [i18n()] },
      attachTo: document.body,
    })
    await flushPromises()

    expect(list).toHaveBeenCalledWith(parent)
    expect(read).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('main.py')
    expect(wrapper.get('tr[aria-current="true"] strong').text()).toBe('main.py')

    const fileLink = wrapper.findAll('a').find((link) => link.text().includes('main.py'))
    expect(fileLink?.classes()).toContain('text-decoration-none')
    await fileLink!.trigger('click')
    await flushPromises()

    expect(read).toHaveBeenCalledWith(path)
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('SOURCE\n')
    wrapper.unmount()
  })

  it('keeps a stale draft and overwrites only after fetching the latest revision', async () => {
    const path = 'data/files/shared.txt'
    const readManagedTextFile = vi.fn()
      .mockResolvedValueOnce({
        path,
        content: 'disk v1',
        revision: 'revision-1',
        capabilities: editableCapabilities,
      })
      .mockResolvedValueOnce({
        path,
        content: 'disk v2',
        revision: 'revision-2',
        capabilities: editableCapabilities,
      })
    const saveManagedTextFile = vi.fn()
      .mockRejectedValueOnce(new ManagementApiError({
        status: 409,
        code: 'text_file_revision_conflict',
        message: 'conflict',
      }))
      .mockResolvedValueOnce({ path, revision: 'revision-3' })
    const wrapper = mount(TextFileEditorSurface, {
      props: {
        path,
        api: { readManagedTextFile, saveManagedTextFile },
      },
      global: { plugins: [i18n()] },
    })
    await flushPromises()

    await wrapper.get('textarea').setValue('my draft')
    const save = wrapper.findAll('button').find((button) => button.text().includes('Save'))
    await save!.trigger('click')
    await flushPromises()

    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('my draft')
    expect(wrapper.text()).toContain('The disk file changed')

    const overwrite = wrapper.findAll('button').find((button) => (
      button.text().includes('Overwrite latest')
    ))
    const overwriteClick = overwrite!.trigger('click')
    await vi.waitFor(() => {
      expect(useConfirmation().current.value?.dangerous).toBe(true)
    })
    expect(readManagedTextFile).toHaveBeenCalledTimes(1)
    useConfirmation().accept()
    await overwriteClick
    await flushPromises()

    expect(readManagedTextFile).toHaveBeenCalledTimes(2)
    expect(saveManagedTextFile).toHaveBeenLastCalledWith(path, 'my draft', 'revision-2')
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('my draft')
  })
})
