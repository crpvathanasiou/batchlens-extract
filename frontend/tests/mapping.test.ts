import { Editor, type JSONContent } from '@tiptap/core'
import { describe, expect, it } from 'vitest'
import { reviewExtensions } from '../src/extensions'
import { editableTextMap, projectPage, sparseChanges, structuralSignature, validateSkeleton } from '../src/mapping'
import { reviewFixture } from './fixture'

describe('document projection', () => {
  it('roundtrips every content node through actual TipTap without semantic edits', () => {
    const server = reviewFixture()
    const canonical = structuredClone(server.document)
    const projected = projectPage(server, 1)
    const editor = new Editor({ injectCSS: false, extensions: reviewExtensions, content: projected.doc })
    const editorDocument = editor.getJSON() as JSONContent
    const texts = editableTextMap(editorDocument)

    expect(projected.unsupported).toEqual([])
    expect(validateSkeleton(structuralSignature(projected.doc), editorDocument)).toEqual([])
    expect(sparseChanges(projected.baselineTexts, editor.getJSON())).toEqual([])
    expect(Object.fromEntries(texts)).toMatchObject({
      'n-parent': 'Parent\n',
      'n-child': 'Child\n\n',
      'n-cell-1': '',
      'n-cell-2': 'A\nB',
      'n-cell-4': '',
      'n-title': 'Title',
      'n-footer': 'Footer\n',
      'n-doc-title': 'Canonical title',
      'n-section': 'Canonical section',
    })
    expect(server.document).toEqual(canonical)
    const table = editorDocument.content?.find((node) => node.type === 'table')
    expect(table?.attrs).toMatchObject({
      sourcePath: 'pages[1].elements[0]',
      rows: 2,
      columns: 3,
    })
    expect(table?.content?.[0].content?.[0].attrs).toMatchObject({
      sourceId: 'n-cell-1',
      sourcePath: 'pages[1].elements[0].cells[0]',
      rowspan: 2,
      colspan: 1,
    })
    expect(table?.content?.[0].content?.[1].attrs).toMatchObject({ colspan: 2 })
    const title = editorDocument.content?.find((node) => node.attrs?.sourceId === 'n-doc-title')
    const section = editorDocument.content?.find((node) => node.attrs?.sourceId === 'n-section')
    expect(title?.content?.[0]).toMatchObject({ type: 'heading', attrs: { level: 2 } })
    expect(section?.content?.[0]).toMatchObject({ type: 'heading', attrs: { level: 3 } })
    expect(title?.content?.[0].type).not.toBe('paragraph')
    editor.destroy()
  })

  it('emits cell edits by cell node id only', () => {
    const projected = projectPage(reviewFixture(), 1)
    const edited = structuredClone(projected.doc)
    const table = edited.content?.find((node) => node.type === 'table')
    table!.content![0].content![1].content![0].content = [{ type: 'text', text: 'changed' }]
    expect(sparseChanges(projected.baselineTexts, edited)).toEqual([
      { node_id: 'n-cell-2', text: 'changed' },
    ])
  })
})
