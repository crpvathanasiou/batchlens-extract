import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { Editor } from '@tiptap/core'
import { describe, expect, it } from 'vitest'
import { loadProtectedContent, pageLoadErrors, reviewExtensions } from '../src/extensions'
import {
  editableTextMap,
  projectPage,
  sparseChanges,
  structuralSignature,
  validateSkeleton,
} from '../src/mapping'
import type { CanonicalDocument, CatalogueNode, ElementContent, ReviewStateResponse, TableGeometry } from '../src/contracts'

const SAMPLE = resolve(
  __dirname,
  '../../out/comparison/fexofenadine-textractor-20260916-173938/document.json',
)

function geometryFor(element: ElementContent, cell?: ElementContent['cells'][number]): TableGeometry | null {
  if (cell) {
    return {
      rows: element.rows,
      columns: element.columns,
      row: cell.row,
      column: cell.column,
      row_span: cell.row_span,
      column_span: cell.column_span,
      header: cell.header,
    }
  }
  if (element.cells.length || element.rows || element.columns) {
    return {
      rows: element.rows,
      columns: element.columns,
      row: null,
      column: null,
      row_span: null,
      column_span: null,
      header: null,
    }
  }
  return null
}

function collectNodes(document: CanonicalDocument): CatalogueNode[] {
  const nodes: CatalogueNode[] = []
  const add = (page: number, path: string, kind: string, text: string, table_geometry: TableGeometry | null) => {
    nodes.push({
      node_id: `${page}:${path}`,
      page_number: page,
      path,
      kind,
      baseline_text: text,
      baseline_hash: `${page}:${path}`,
      reference_ids: [],
      references: [],
      table_geometry,
    })
  }
  const walk = (page: number, path: string, element: ElementContent) => {
    add(page, path, element.kind, element.text, geometryFor(element))
    element.children.forEach((child, index) => walk(page, `${path}.children[${index}]`, child))
    element.cells.forEach((cell, index) => add(page, `${path}.cells[${index}]`, 'TABLE_CELL', cell.text, geometryFor(element, cell)))
    element.titles.forEach((title, index) => add(page, `${path}.titles[${index}]`, 'TITLE', title.text, null))
    element.footers.forEach((footer, index) => add(page, `${path}.footers[${index}]`, 'FOOTER', footer.text, null))
  }
  for (const page of document.pages) {
    page.elements.forEach((element, index) => walk(page.number, `pages[${page.number}].elements[${index}]`, element))
  }
  return nodes
}

function reviewStateFromDocument(document: CanonicalDocument): ReviewStateResponse {
  const nodes = collectNodes(document)
  return {
    status: 'NOT_REVIEWED',
    revision_id: null,
    generation: 0,
    revision: null,
    source_page_count: document.pages.length,
    document,
    catalogue: {
      baseline: { key: 'document.json', version: '1', content_type: 'application/json' },
      nodes,
      catalogue_hash: 'sample',
    },
    pages: document.pages.map((page) => ({ page_number: page.number, content_hash: `page-${page.number}`, approval: null })),
    findings: [],
  }
}

const describeSample = existsSync(SAMPLE) ? describe : describe.skip

describeSample('real fexofenadine editor round trip', () => {
  const document = JSON.parse(readFileSync(SAMPLE, 'utf8')) as CanonicalDocument
  const server = reviewStateFromDocument(document)
  const pages = document.pages.map((page) => page.number).sort((left, right) => left - right)

  it('validates every projected page through the production editor schema', () => {
    expect(pages).toHaveLength(18)
    const failures: string[] = []
    for (const page of pages) {
      const projected = projectPage(server, page)
      if (projected.unsupported.length) {
        failures.push(`page ${page}: ${projected.unsupported.join('; ')}`)
        continue
      }
      const editor = new Editor({ injectCSS: false, extensions: reviewExtensions, content: projected.doc })
      const json = editor.getJSON()
      const errors = [
        ...validateSkeleton(structuralSignature(projected.doc), json),
        ...sparseChanges(projected.baselineTexts, json).map((change) => `${change.node_id} changed`),
      ]
      if (errors.length) failures.push(`page ${page}: ${errors.join('; ')}`)
      editor.destroy()
    }
    expect(failures).toEqual([])
  })

  it('loads pages sequentially including 18 back to 1', () => {
    const first = projectPage(server, pages[0]).doc
    const editor = new Editor({ injectCSS: false, extensions: reviewExtensions, content: first })
    const visited: number[] = []
    for (const page of [...pages, pages[0]]) {
      const projected = projectPage(server, page)
      expect(loadProtectedContent(editor, projected.doc)).toBe(true)
      expect(pageLoadErrors(projected.doc, editor.getJSON())).toEqual([])
      const texts = editableTextMap(editor.getJSON())
      const sample = server.catalogue.nodes.find((node) => node.page_number === page)
      expect(sample && texts.has(sample.node_id)).toBe(true)
      for (const nodeId of texts.keys()) {
        expect(server.catalogue.nodes.find((node) => node.node_id === nodeId)?.page_number).toBe(page)
      }
      visited.push(page)
    }
    editor.destroy()
    expect(visited.at(-1)).toBe(1)
    expect(visited.at(-2)).toBe(18)
  })
})
