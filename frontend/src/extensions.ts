import { Extension, Node, type Editor, type Extensions, type JSONContent } from '@tiptap/core'
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table'
import { Fragment, Slice, type DOMOutputSpec } from '@tiptap/pm/model'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet, type EditorView } from '@tiptap/pm/view'
import StarterKit from '@tiptap/starter-kit'
import { structuralSignature, validateSkeleton } from './mapping'

export const SourceRegion = Node.create({
  name: 'sourceRegion',
  group: 'block',
  content: '(paragraph | heading)+',
  defining: true,
  isolating: true,
  selectable: false,
  addAttributes() {
    return {
      sourceId: { default: null },
      sourcePage: { default: null },
      sourceKind: { default: 'text' },
      sourcePath: { default: null },
      readOnly: { default: false },
      lockedText: { default: null },
    }
  },
  parseHTML() {
    return [{ tag: 'section[data-source-region]' }]
  },
  renderHTML({ node }) {
    return [
      'section',
      {
        'data-source-region': node.attrs.sourceId,
        'data-source-page': node.attrs.sourcePage,
        'data-source-kind': node.attrs.sourceKind,
        'data-read-only': node.attrs.readOnly ? 'true' : undefined,
      },
      0,
    ]
  },
})

function cellHtmlAttributes(tag: 'td' | 'th', node: { attrs: Record<string, unknown> }): DOMOutputSpec {
  return [
    tag,
    {
      colspan: Number(node.attrs.colspan) === 1 ? undefined : node.attrs.colspan,
      rowspan: Number(node.attrs.rowspan) === 1 ? undefined : node.attrs.rowspan,
      'data-source-cell': node.attrs.sourceId,
      'data-read-only': node.attrs.readOnly ? 'true' : undefined,
    },
    0,
  ]
}

const cellAttributes = () => ({
  sourceId: {
    default: null,
    parseHTML: (element: HTMLElement) => element.getAttribute('data-source-cell'),
    renderHTML: ({ sourceId }: { sourceId?: string | null }) =>
      sourceId ? { 'data-source-cell': sourceId } : {},
  },
  sourcePage: { default: null },
  sourcePath: { default: null },
  readOnly: { default: false },
  lockedText: { default: null },
})

const ProtectedTableCell = TableCell.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      ...cellAttributes(),
    }
  },
  renderHTML({ node }) {
    return cellHtmlAttributes('td', node)
  },
})

const ProtectedTableHeader = TableHeader.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      ...cellAttributes(),
    }
  },
  renderHTML({ node }) {
    return cellHtmlAttributes('th', node)
  },
})

const ProtectedTable = Table.extend({
  addAttributes() {
    // sourcePath/rows/columns must round-trip or structural validation diverges from projection.
    return {
      ...this.parent?.(),
      sourcePath: { default: null },
      rows: { default: null },
      columns: { default: null },
    }
  },
})

const highlightKey = new PluginKey<{ nodeId: string | null }>('sourceHighlight')
const toleranceMarkerKey = new PluginKey<{ nodeIds: string[] }>('toleranceMarker')
const TOLERANCE_MARKER_TYPES = new Set(['sourceRegion', 'tableCell', 'tableHeader'])
export const TOLERANCE_MARKER_TITLE = 'Possible ± tolerance — review this value.'

type ProtectedStorage = { expected: unknown }

export const ProtectedStructure = Extension.create({
  name: 'protectedStructure',
  priority: 10_000,
  addStorage() {
    return { expected: null as unknown }
  },
  onCreate() {
    this.storage.expected = structuralSignature(this.editor.getJSON())
  },
  addProseMirrorPlugins() {
    const editor = this.editor
    return [
      new Plugin({
        filterTransaction(transaction, state) {
          if (!transaction.docChanged) return true
          // Reject edits that would change IDs, table geometry, or heading levels.
          const storage = editor.storage as unknown as Record<string, ProtectedStorage>
          const expected = storage.protectedStructure.expected ?? structuralSignature(state.doc.toJSON())
          return validateSkeleton(expected, transaction.doc.toJSON()).length === 0
        },
      }),
      new Plugin({
        key: highlightKey,
        state: {
          init: () => ({ nodeId: null as string | null }),
          apply(transaction, value) {
            const next = transaction.getMeta(highlightKey) as { nodeId: string | null } | undefined
            return next ?? value
          },
        },
        props: {
          decorations(state) {
            const nodeId = highlightKey.getState(state)?.nodeId
            if (!nodeId) return null
            const decorations: Decoration[] = []
            state.doc.descendants((node, position) => {
              if (node.attrs.sourceId === nodeId) {
                decorations.push(Decoration.node(position, position + node.nodeSize, { class: 'bl-source-highlight' }))
              }
            })
            return DecorationSet.create(state.doc, decorations)
          },
        },
      }),
      new Plugin({
        key: toleranceMarkerKey,
        state: {
          init: () => ({ nodeIds: [] as string[] }),
          apply(transaction, value) {
            const next = transaction.getMeta(toleranceMarkerKey) as { nodeIds: string[] } | undefined
            return next ?? value
          },
        },
        props: {
          decorations(state) {
            const nodeIds = new Set(toleranceMarkerKey.getState(state)?.nodeIds ?? [])
            if (!nodeIds.size) return null
            const decorations: Decoration[] = []
            state.doc.descendants((node, position) => {
              if (
                TOLERANCE_MARKER_TYPES.has(node.type.name) &&
                typeof node.attrs.sourceId === 'string' &&
                nodeIds.has(node.attrs.sourceId)
              ) {
                decorations.push(
                  Decoration.node(position, position + node.nodeSize, {
                    class: 'bl-tolerance-warning',
                    title: TOLERANCE_MARKER_TITLE,
                  }),
                )
              }
            })
            return DecorationSet.create(state.doc, decorations)
          },
        },
      }),
    ]
  },
  addKeyboardShortcuts() {
    return {
      Enter: () => this.editor.commands.setHardBreak(),
      Tab: () => this.editor.isActive('table'),
      'Shift-Tab': () => this.editor.isActive('table'),
    }
  },
})

export function highlightSource(editor: Editor, nodeId: string | null) {
  editor.view.dispatch(editor.state.tr.setMeta(highlightKey, { nodeId }))
}

export function setToleranceMarkers(editor: Editor, nodeIds: string[]) {
  editor.view.dispatch(editor.state.tr.setMeta(toleranceMarkerKey, { nodeIds: [...nodeIds] }))
}

export const reviewExtensions: Extensions = [
  StarterKit.configure({
    blockquote: false,
    bold: false,
    bulletList: false,
    code: false,
    codeBlock: false,
    dropcursor: false,
    gapcursor: false,
    heading: { levels: [2, 3] },
    horizontalRule: false,
    italic: false,
    listItem: false,
    orderedList: false,
    strike: false,
    underline: false,
    trailingNode: false,
  }),
  SourceRegion,
  ProtectedTable.configure({ resizable: false, allowTableNodeSelection: false }),
  TableRow,
  ProtectedTableHeader,
  ProtectedTableCell,
  ProtectedStructure,
]

export function loadProtectedContent(editor: Editor, content: JSONContent): boolean {
  // On failure, restore the previous skeleton so a rejected page load cannot keep showing another page.
  const storage = editor.storage as unknown as Record<string, { expected: unknown }>
  const previous = storage.protectedStructure.expected
  storage.protectedStructure.expected = structuralSignature(content)
  const loaded = editor.commands.setContent(content, { emitUpdate: false, errorOnInvalidContent: true })
  if (!loaded || pageLoadErrors(content, editor.getJSON()).length) {
    storage.protectedStructure.expected = previous ?? structuralSignature(editor.getJSON())
    return false
  }
  return true
}

export function pageLoadErrors(intended: JSONContent, loaded: JSONContent): string[] {
  const errors = validateSkeleton(structuralSignature(intended), loaded)
  const intendedPage = firstSourcePage(intended)
  const loadedPage = firstSourcePage(loaded)
  if (intendedPage !== loadedPage) {
    errors.push(`Loaded page ${String(loadedPage)} does not match selected page ${String(intendedPage)}.`)
  }
  return errors
}

function firstSourcePage(doc: JSONContent): unknown {
  const visit = (node: JSONContent): unknown => {
    if (typeof node.attrs?.sourcePage === 'number') return node.attrs.sourcePage
    for (const child of node.content ?? []) {
      const page = visit(child)
      if (page !== undefined) return page
    }
    return undefined
  }
  return visit(doc)
}

export const protectedEditorProps = {
  handleDrop: () => true,
  handlePaste: (view: EditorView, event: ClipboardEvent) => {
    if (event.clipboardData?.getData('text/html')) return true
    const text = event.clipboardData?.getData('text/plain')
    if (!text) return false
    const { $from, $to } = view.state.selection
    const sourceAt = (position: typeof $from) => {
      for (let depth = position.depth; depth >= 0; depth -= 1) {
        const id = position.node(depth).attrs.sourceId
        if (typeof id === 'string') return id
      }
      return null
    }
    if (!sourceAt($from) || sourceAt($from) !== sourceAt($to)) return true
    const hardBreak = view.state.schema.nodes.hardBreak
    const content = text.split('\n').flatMap((line, index) => [
      ...(index && hardBreak ? [hardBreak.create()] : []),
      ...(line ? [view.state.schema.text(line)] : []),
    ])
    view.dispatch(
      view.state.tr.replaceSelection(new Slice(Fragment.fromArray(content), 0, 0)).scrollIntoView(),
    )
    return true
  },
  handleDOMEvents: {
    cut: () => true,
  },
}
