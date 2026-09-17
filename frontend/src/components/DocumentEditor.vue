<script setup lang="ts">
import type { JSONContent } from '@tiptap/core'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import { nextTick, ref, watch } from 'vue'
import { highlightSource, loadProtectedContent, pageLoadErrors, protectedEditorProps, reviewExtensions, setToleranceMarkers } from '../extensions'
import { sameEditableDocument } from '../mapping'

const props = defineProps<{
  content: JSONContent
  disabled?: boolean
  toleranceNodeIds?: string[]
}>()

const emit = defineEmits<{
  update: [content: JSONContent]
  contentError: [message: string]
}>()
const editorRoot = ref<HTMLElement>()
const suppressUpdates = ref(false)
let highlightTimer: ReturnType<typeof setTimeout> | undefined

const editor = useEditor({
  content: props.content,
  extensions: reviewExtensions,
  editable: !props.disabled,
  injectCSS: false,
  editorProps: protectedEditorProps,
  onUpdate: ({ editor }) => {
    if (!suppressUpdates.value) emit('update', editor.getJSON())
  },
  onContentError: ({ error }) => emit('contentError', error.message),
})

function applyContent(content: JSONContent) {
  const instance = editor.value
  if (!instance || sameEditableDocument(instance.getJSON(), content)) return
  suppressUpdates.value = true
  const loaded = loadProtectedContent(instance, content)
  const actual = instance.getJSON()
  const errors = loaded ? pageLoadErrors(content, actual) : ['Unable to load the selected page.']
  void nextTick(() => {
    suppressUpdates.value = false
  })
  if (errors.length) {
    emit('contentError', errors[0])
    return
  }
}

watch(
  () => props.disabled,
  (disabled) => {
    const instance = editor.value
    if (!instance) return
    suppressUpdates.value = true
    instance.setEditable(!disabled)
    void nextTick(() => {
      suppressUpdates.value = false
    })
  },
)

watch(
  [editor, () => props.content],
  () => {
    if (editor.value) applyContent(props.content)
  },
)

watch(
  [editor, () => props.toleranceNodeIds],
  () => {
    const instance = editor.value
    if (!instance) return
    suppressUpdates.value = true
    setToleranceMarkers(instance, props.toleranceNodeIds ?? [])
    void nextTick(() => {
      suppressUpdates.value = false
    })
  },
)

function cssEscape(value: string): string {
  const css = globalThis.CSS
  if (css && typeof css.escape === 'function') return css.escape(value)
  return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
}

async function focusNode(nodeId: string) {
  await nextTick()
  const instance = editor.value
  if (!instance) return
  const selector = `[data-source-region="${cssEscape(nodeId)}"],[data-source-cell="${cssEscape(nodeId)}"]`
  const scope = editorRoot.value ?? instance.view.dom
  const element = scope.querySelector<HTMLElement>(selector)
  if (!element) {
    emit('contentError', `Unable to locate source region ${nodeId} on the displayed page.`)
    return
  }
  element.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
  suppressUpdates.value = true
  highlightSource(instance, nodeId)
  void nextTick(() => {
    suppressUpdates.value = false
  })
  if (highlightTimer !== undefined) clearTimeout(highlightTimer)
  highlightTimer = setTimeout(() => highlightSource(instance, null), 1800)
}

defineExpose({ focusNode, getJSON: () => editor.value?.getJSON() })
</script>

<template>
  <section ref="editorRoot" class="bl-editor" aria-label="Extracted document editor">
    <div v-if="editor" class="bl-editor__toolbar" role="toolbar" aria-label="Text formatting">
      <button type="button" :disabled="!editor.can().undo()" @click="editor.chain().focus().undo().run()">Undo</button>
      <button type="button" :disabled="!editor.can().redo()" @click="editor.chain().focus().redo().run()">Redo</button>
      <span class="bl-toolbar-spacer" />
      <button type="button" :disabled="disabled" aria-label="Insert plus-minus symbol" @click="editor.chain().focus().insertContent('±').run()">Insert ±</button>
    </div>
    <EditorContent
      v-if="editor"
      :editor="editor"
      class="bl-editor__content"
    />
  </section>
</template>
