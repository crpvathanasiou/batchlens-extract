import { Editor, type JSONContent } from '@tiptap/core'
import { describe, expect, it, vi } from 'vitest'
import { loadProtectedContent, pageLoadErrors, reviewExtensions } from '../src/extensions'
import { editableTextMap, projectPage, sparseChanges, structuralSignature, validateSkeleton } from '../src/mapping'
import { createReviewState } from '../src/state'
import { reviewFixture } from './fixture'
import type { ReviewApi } from '../src/api'

function makeEditor(content: JSONContent) {
  return new Editor({ injectCSS: false, extensions: reviewExtensions, content })
}

function replaceNodeText(editor: Editor, nodeId: string, text: string) {
  let from = 0
  let to = 0
  editor.state.doc.descendants((node, position) => {
    if (node.attrs.sourceId !== nodeId || !node.childCount) return
    from = position + 2
    to = from + node.child(0).content.size
    return false
  })
  editor.commands.setTextSelection({ from, to })
  expect(editor.commands.insertContent(text)).toBe(true)
}

describe('actual editor round trip', () => {
  it('preserves table metadata, blank cells, newlines, merged spans, and headings', () => {
    const projected = projectPage(reviewFixture(), 1)
    const editor = makeEditor(projected.doc)
    const json = editor.getJSON()
    expect(validateSkeleton(structuralSignature(projected.doc), json)).toEqual([])
    expect(sparseChanges(projected.baselineTexts, json)).toEqual([])
    expect(Object.fromEntries(editableTextMap(json))).toMatchObject({
      'n-cell-1': '',
      'n-cell-2': 'A\nB',
      'n-cell-4': '',
      'n-doc-title': 'Canonical title',
      'n-section': 'Canonical section',
    })
    const table = json.content?.find((node) => node.type === 'table')
    expect(table?.attrs).toMatchObject({ sourcePath: 'pages[1].elements[0]', rows: 2, columns: 3 })
    expect(editor.getHTML()).toContain('data-source-cell="n-cell-1"')
    expect(editor.getHTML()).toContain('data-source-cell="n-cell-2"')
    expect(editor.getHTML()).toContain('<th')
    expect(editor.getHTML()).toContain('<td')
    expect(editor.getHTML()).toContain('<h2>')
    expect(editor.getHTML()).toContain('<h3>')
    editor.destroy()
  })

  it('saves a cell edit from actual editor JSON through the real state layer', async () => {
    const server = reviewFixture()
    const save = vi.fn().mockResolvedValue({ ...server, status: 'IN_REVIEW', revision_id: 'revision-1' })
    const api: ReviewApi = {
      load: vi.fn().mockResolvedValue(server),
      save,
      approvePage: vi.fn().mockResolvedValue(server),
      approve: vi.fn().mockResolvedValue(server),
      exportUrl: vi.fn().mockResolvedValue('/export'),
      fetchSource: vi.fn(),
    }
    const review = createReviewState(api)
    await review.load()
    const editor = makeEditor(review.state.drafts[1])
    replaceNodeText(editor, 'n-cell-2', 'edited-cell')
    const json = editor.getJSON()
    expect(validateSkeleton(review.state.skeletons[1], json)).toEqual([])
    review.setDraft(json)
    await review.save()
    expect(save).toHaveBeenCalledTimes(1)
    expect(save).toHaveBeenCalledWith(null, [{ node_id: 'n-cell-2', text: 'edited-cell' }], [])
    editor.destroy()
  })

  it('navigates page 1 to page 2 to page 1 without mixing table drafts', () => {
    const server = reviewFixture()
    const pageOne = projectPage(server, 1).doc
    const pageTwo = projectPage(server, 2).doc
    const drafts: Record<number, JSONContent> = { 1: pageOne, 2: pageTwo }
    const editor = makeEditor(drafts[1])
    replaceNodeText(editor, 'n-cell-2', 'page-one-cell')
    drafts[1] = editor.getJSON()
    expect(loadProtectedContent(editor, drafts[2])).toBe(true)
    expect(pageLoadErrors(drafts[2], editor.getJSON())).toEqual([])
    expect(editableTextMap(editor.getJSON()).get('n-page-2-cell-2')).toBe('P2B')
    expect(editableTextMap(editor.getJSON()).has('n-cell-2')).toBe(false)
    replaceNodeText(editor, 'n-page-2-cell-2', 'page-two-cell')
    drafts[2] = editor.getJSON()
    expect(loadProtectedContent(editor, drafts[1])).toBe(true)
    expect(pageLoadErrors(drafts[1], editor.getJSON())).toEqual([])
    expect(editableTextMap(editor.getJSON()).get('n-cell-2')).toBe('page-one-cell')
    expect(editableTextMap(editor.getJSON()).get('n-page-2-cell-2')).toBeUndefined()
    expect(editableTextMap(drafts[2]).get('n-page-2-cell-2')).toBe('page-two-cell')
    editor.destroy()
  })

  it('keeps cell DOM identities after a text edit', () => {
    const editor = makeEditor(projectPage(reviewFixture(), 1).doc)
    replaceNodeText(editor, 'n-cell-3', 'C2')
    const html = editor.getHTML()
    expect(html).toContain('data-source-cell="n-cell-3"')
    expect(html).toContain('data-source-cell="n-cell-1"')
    expect(html).toMatch(/<th[^>]*data-source-cell="n-cell-2"/)
    expect(html).toMatch(/<td[^>]*data-source-cell="n-cell-3"/)
    editor.destroy()
  })
})
