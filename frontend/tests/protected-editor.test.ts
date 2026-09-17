import { Editor, type JSONContent } from '@tiptap/core'
import { describe, expect, it } from 'vitest'
import { loadProtectedContent, protectedEditorProps, reviewExtensions } from '../src/extensions'
import { projectPage, structuralSignature, validateSkeleton, editableTextMap } from '../src/mapping'
import { reviewFixture } from './fixture'

describe('protected editor structure', () => {
  function editor() {
    return new Editor({
      injectCSS: false,
      extensions: reviewExtensions,
      content: projectPage(reviewFixture(), 1).doc,
    })
  }

  it('allows text replacement while rejecting region deletion and duplicate ids', () => {
    const instance = editor()
    instance.commands.setTextSelection({ from: 2, to: 8 })
    expect(instance.commands.insertContent('edited')).toBe(true)
    expect(instance.getText()).toContain('edited')

    const before = instance.getJSON()
    instance.view.dispatch(instance.state.tr.delete(0, instance.state.doc.child(0).nodeSize))
    expect(instance.getJSON()).toEqual(before)

    let secondRegion = 0
    instance.state.doc.descendants((node, position) => {
      if (node.type.name === 'sourceRegion' && node.attrs.sourceId === 'n-child') secondRegion = position
    })
    instance.view.dispatch(instance.state.tr.setNodeMarkup(secondRegion, undefined, {
      ...instance.state.doc.nodeAt(secondRegion)?.attrs,
      sourceId: 'n-parent',
    }))
    expect(instance.getJSON()).toEqual(before)
    instance.destroy()
  })

  it('blocks HTML paste and normalizes plain text newlines within one source node', () => {
    const instance = editor()
    instance.commands.setTextSelection(2)
    const before = instance.getJSON()
    const htmlEvent = {
      clipboardData: { getData: (type: string) => type === 'text/html' ? '<b>unsafe</b>' : 'unsafe' },
    } as ClipboardEvent
    expect(protectedEditorProps.handlePaste(instance.view, htmlEvent)).toBe(true)
    expect(instance.getJSON()).toEqual(before)

    const textEvent = {
      clipboardData: { getData: (type: string) => type === 'text/plain' ? 'one\ntwo' : '' },
    } as ClipboardEvent
    expect(protectedEditorProps.handlePaste(instance.view, textEvent)).toBe(true)
    const pasted = instance.getJSON() as JSONContent
    expect(pasted.content?.[0].content?.[0].content?.some((node: JSONContent) => node.type === 'hardBreak')).toBe(true)
    instance.destroy()
  })

  it('rejects table span changes and heading level changes', () => {
    const instance = editor()
    let cellPosition = 0
    let headingPosition = 0
    instance.state.doc.descendants((node, position) => {
      if (node.attrs.sourceId === 'n-cell-2') cellPosition = position
      if (node.type.name === 'heading' && node.attrs.level === 2) headingPosition = position
    })
    const before = instance.getJSON()
    const cell = instance.state.doc.nodeAt(cellPosition)!
    instance.view.dispatch(instance.state.tr.setNodeMarkup(cellPosition, undefined, { ...cell.attrs, colspan: 1 }))
    expect(instance.getJSON()).toEqual(before)
    const heading = instance.state.doc.nodeAt(headingPosition)!
    instance.view.dispatch(instance.state.tr.setNodeMarkup(headingPosition, undefined, { ...heading.attrs, level: 3 }))
    expect(instance.getJSON()).toEqual(before)
    instance.destroy()
  })

  it('keeps table metadata through an actual page load', () => {
    const server = reviewFixture()
    const pageOne = projectPage(server, 1).doc
    const pageTwo = projectPage(server, 2).doc
    const instance = new Editor({ injectCSS: false, extensions: reviewExtensions, content: pageOne })
    expect(validateSkeleton(structuralSignature(pageOne), instance.getJSON())).toEqual([])
    expect(loadProtectedContent(instance, pageTwo)).toBe(true)
    expect(validateSkeleton(structuralSignature(pageTwo), instance.getJSON())).toEqual([])
    expect(editableTextMap(instance.getJSON()).has('n-page-2-cell-1')).toBe(true)
    expect(editableTextMap(instance.getJSON()).has('n-cell-2')).toBe(false)
    instance.destroy()
  })
})
