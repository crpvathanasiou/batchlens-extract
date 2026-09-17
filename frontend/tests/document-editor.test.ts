import { nextTick, ref } from 'vue'
import { createApp, type App } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import DocumentEditor from '../src/components/DocumentEditor.vue'
import { editableTextMap, projectPage } from '../src/mapping'
import { reviewFixture } from './fixture'
import type { JSONContent } from '@tiptap/core'

interface MountedEditor {
  app: App
  host: HTMLElement
  page: ReturnType<typeof ref<JSONContent>>
  updates: JSONContent[]
  errors: string[]
  editor: { focusNode: (nodeId: string) => Promise<void>; getJSON: () => JSONContent | undefined }
}

const mounts: MountedEditor[] = []

async function mountEditor(content: JSONContent): Promise<MountedEditor> {
  const page = ref(content)
  const updates: JSONContent[] = []
  const errors: string[] = []
  const host = document.createElement('div')
  document.body.appendChild(host)
  const editorRef = ref()
  const app = createApp({
    components: { DocumentEditor },
    setup() {
      return {
        page,
        editorRef,
        onUpdate: (doc: JSONContent) => updates.push(doc),
        onError: (message: string) => errors.push(message),
      }
    },
    template:
      '<DocumentEditor ref="editorRef" :content="page" @update="onUpdate" @content-error="onError" />',
  })
  app.mount(host)
  await nextTick()
  await nextTick()
  const mounted: MountedEditor = {
    app,
    host,
    page,
    updates,
    errors,
    editor: editorRef.value,
  }
  mounts.push(mounted)
  return mounted
}

afterEach(() => {
  while (mounts.length) {
    const mounted = mounts.pop()
    mounted?.app.unmount()
    mounted?.host.remove()
  }
})

describe('DocumentEditor page loading', () => {
  it('loads another table page and restores the first page draft', async () => {
    const server = reviewFixture()
    const pageOne = projectPage(server, 1).doc
    const pageTwo = projectPage(server, 2).doc
    const mounted = await mountEditor(pageOne)
    expect(mounted.editor.getJSON()).toBeTruthy()
    expect(editableTextMap(mounted.editor.getJSON()!).has('n-cell-2')).toBe(true)
    expect(mounted.host.querySelector('[data-source-cell="n-cell-2"]')).not.toBeNull()

    mounted.page.value = pageTwo
    await nextTick()
    await nextTick()
    expect(mounted.errors).toEqual([])
    expect(editableTextMap(mounted.editor.getJSON()!).has('n-page-2-cell-1')).toBe(true)
    expect(mounted.host.querySelector('[data-source-cell="n-page-2-cell-1"]')).not.toBeNull()
    expect(mounted.host.querySelector('[data-source-cell="n-cell-2"]')).toBeNull()
    expect(mounted.updates).toEqual([])

    mounted.page.value = pageOne
    await nextTick()
    await nextTick()
    expect(mounted.errors).toEqual([])
    expect(editableTextMap(mounted.editor.getJSON()!).get('n-cell-2')).toBe('A\nB')
    expect(mounted.host.querySelector('[data-source-cell="n-cell-2"]')).not.toBeNull()
  })

  it('highlights only the requested cell after a page change', async () => {
    const server = reviewFixture()
    const mounted = await mountEditor(projectPage(server, 1).doc)
    mounted.page.value = projectPage(server, 2).doc
    await nextTick()
    await nextTick()
    expect(mounted.host.querySelector('[data-source-cell="n-page-2-cell-1"]')).not.toBeNull()
    expect(mounted.host.querySelector('[data-source-cell="n-page-2-cell-2"]')).not.toBeNull()
    await mounted.editor.focusNode('n-page-2-cell-2')
    expect(mounted.errors).toEqual([])
    const cell = mounted.host.querySelector('[data-source-cell="n-page-2-cell-2"]')
    const highlighted = [...mounted.host.querySelectorAll('.bl-source-highlight')]
    expect(cell).not.toBeNull()
    expect(cell?.classList.contains('bl-source-highlight')).toBe(true)
    expect(highlighted).toHaveLength(1)
    expect(highlighted[0].getAttribute('data-source-cell')).toBe('n-page-2-cell-2')
    expect(editableTextMap(mounted.editor.getJSON()!).get('n-page-2-cell-2')).toBe('P2B')
    expect(mounted.updates).toEqual([])
  })
})
