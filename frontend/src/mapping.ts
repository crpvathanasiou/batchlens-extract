import type { JSONContent } from '@tiptap/core'
import type {
  CanonicalPage,
  CatalogueNode,
  Content,
  ElementContent,
  RequestedChange,
  ReviewStateResponse,
} from './contracts'

const textNode = (text: string): JSONContent[] => (text ? [{ type: 'text', text }] : [])

export function textContent(text: string): JSONContent[] {
  const lines = text.split('\n')
  return lines.flatMap((line, index) => [
    ...(index ? [{ type: 'hardBreak' } satisfies JSONContent] : []),
    ...textNode(line),
  ])
}

export function headingLevel(kind: string | undefined): 2 | 3 | null {
  // Canonical lowercase title/section_heading only. Table-title TITLE stays a non-heading region.
  if (kind === 'title') return 2
  if (kind === 'section_heading') return 3
  return null
}

function innerBlock(kind: string | undefined, text: string): JSONContent {
  const level = headingLevel(kind)
  if (level) return { type: 'heading', attrs: { level }, content: textContent(text) }
  return { type: 'paragraph', content: textContent(text) }
}

export interface PageProjection {
  doc: JSONContent
  baselineTexts: Map<string, string>
  unsupported: string[]
}

function textRegion(
  node: CatalogueNode | undefined,
  content: Content,
  path: string,
  page: number,
  unsupported: string[],
): JSONContent {
  if (!node) unsupported.push(`Missing catalogue node: ${path}`)
  return {
    type: 'sourceRegion',
    attrs: {
      sourceId: node?.node_id ?? null,
      sourcePage: page,
      sourceKind: node?.kind ?? 'UNSUPPORTED',
      sourcePath: path,
      readOnly: !node,
      lockedText: node ? null : content.text,
    },
    content: [innerBlock(node?.kind, content.text)],
  }
}

function projectTable(
  element: ElementContent,
  path: string,
  page: number,
  byPath: Map<string, CatalogueNode>,
  unsupported: string[],
): JSONContent | null {
  if (!element.cells.length) return null
  const rows = new Map<number, { column: number; node: JSONContent }[]>()
  for (let index = 0; index < element.cells.length; index += 1) {
    const cell = element.cells[index]
    const cellPath = `${path}.cells[${index}]`
    const node = byPath.get(cellPath)
    if (!node) unsupported.push(`Missing catalogue node: ${cellPath}`)
    if (
      !node?.table_geometry ||
      node.table_geometry.row !== cell.row ||
      node.table_geometry.column !== cell.column ||
      node.table_geometry.row_span !== cell.row_span ||
      node.table_geometry.column_span !== cell.column_span
    ) {
      unsupported.push(`Unsupported table geometry: ${cellPath}`)
    }
    const projected: JSONContent = {
      type: cell.header ? 'tableHeader' : 'tableCell',
      attrs: {
        sourceId: node?.node_id ?? null,
        sourcePage: page,
        sourcePath: cellPath,
        readOnly: !node,
        lockedText: node ? null : cell.text,
        colspan: cell.column_span,
        rowspan: cell.row_span,
        colwidth: null,
      },
      content: [{ type: 'paragraph', content: textContent(cell.text) }],
    }
    rows.set(cell.row, [...(rows.get(cell.row) ?? []), { column: cell.column, node: projected }])
  }
  if (rows.size !== element.rows || element.columns < 1) unsupported.push(`Incomplete table: ${path}`)
  return {
    type: 'table',
    attrs: { sourcePath: path, rows: element.rows, columns: element.columns },
    content: [...rows.entries()]
      .sort(([left], [right]) => left - right)
      .map(([, cells]) => ({
        type: 'tableRow',
        content: cells.sort((left, right) => left.column - right.column).map((item) => item.node),
      })),
  }
}

function plainText(node: JSONContent): string {
  if (node.type === 'text') return node.text ?? ''
  if (node.type === 'hardBreak') return '\n'
  return (node.content ?? []).map(plainText).join('')
}

function projectElement(
  element: ElementContent,
  path: string,
  page: number,
  byPath: Map<string, CatalogueNode>,
  unsupported: string[],
): JSONContent[] {
  const result: JSONContent[] = [textRegion(byPath.get(path), element, path, page, unsupported)]
  element.children.forEach((child, index) => {
    result.push(...projectElement(child, `${path}.children[${index}]`, page, byPath, unsupported))
  })
  const table = projectTable(element, path, page, byPath, unsupported)
  if (table) result.push(table)
  element.titles.forEach((title, index) => {
    const childPath = `${path}.titles[${index}]`
    result.push(textRegion(byPath.get(childPath), title, childPath, page, unsupported))
  })
  element.footers.forEach((footer, index) => {
    const childPath = `${path}.footers[${index}]`
    result.push(textRegion(byPath.get(childPath), footer, childPath, page, unsupported))
  })
  return result
}

export function projectPage(state: ReviewStateResponse, pageNumber: number): PageProjection {
  const page: CanonicalPage | undefined = state.document.pages.find((item) => item.number === pageNumber)
  const unsupported: string[] = []
  if (!page) return { doc: { type: 'doc', content: [] }, baselineTexts: new Map(), unsupported: ['Canonical page missing.'] }
  const nodes = state.catalogue.nodes.filter((node) => node.page_number === pageNumber)
  const byPath = new Map(nodes.map((node) => [node.path, node]))
  if (byPath.size !== nodes.length) unsupported.push('Duplicate catalogue paths.')
  const content = page.elements.flatMap((element, index) =>
    projectElement(element, `pages[${page.number}].elements[${index}]`, page.number, byPath, unsupported),
  )
  const doc = { type: 'doc', content } satisfies JSONContent
  const sourceIds = nodes.map((node) => node.node_id)
  if (new Set(sourceIds).size !== sourceIds.length) unsupported.push('Duplicate source node IDs.')
  const represented = new Set(editableTextMap(doc).keys())
  for (const node of nodes) if (!represented.has(node.node_id)) unsupported.push(`Unprojected catalogue node: ${node.path}`)
  return {
    doc,
    baselineTexts: new Map(nodes.map((node) => [node.node_id, currentTextAtPath(state.document, node.path)])),
    unsupported,
  }
}

export function editableTextMap(doc: JSONContent): Map<string, string> {
  const result = new Map<string, string>()
  const visit = (node: JSONContent) => {
    if (
      (node.type === 'sourceRegion' || node.type === 'tableCell' || node.type === 'tableHeader') &&
      typeof node.attrs?.sourceId === 'string'
    ) {
      result.set(node.attrs.sourceId, plainText(node))
      return
    }
    node.content?.forEach(visit)
  }
  visit(doc)
  return result
}

export function sparseChanges(baseline: Map<string, string>, edited: JSONContent): RequestedChange[] {
  return [...editableTextMap(edited)]
    .filter(([id, text]) => baseline.get(id) !== text)
    .map(([node_id, text]) => ({ node_id, text }))
}

function numericAttr(value: unknown): unknown {
  if (value == null || value === '') return value
  const asNumber = Number(value)
  return Number.isFinite(asNumber) ? asNumber : value
}

export function structuralSignature(node: JSONContent): unknown {
  // Protected skeleton: IDs, paths, table geometry, and heading levels. Text is excluded.
  if (node.type === 'sourceRegion') {
    return [
      node.type,
      {
        sourceId: node.attrs?.sourceId,
        sourcePage: node.attrs?.sourcePage,
        sourceKind: node.attrs?.sourceKind,
        sourcePath: node.attrs?.sourcePath,
        readOnly: node.attrs?.readOnly,
        lockedText: node.attrs?.lockedText,
      },
      (node.content ?? []).map((child) =>
        child.type === 'heading' ? [child.type, numericAttr(child.attrs?.level)] : child.type,
      ),
    ]
  }
  if (node.type === 'heading') {
    return [node.type, numericAttr(node.attrs?.level)]
  }
  if (node.type === 'table') {
    return [
      node.type,
      node.attrs?.sourcePath,
      numericAttr(node.attrs?.rows),
      numericAttr(node.attrs?.columns),
      (node.content ?? []).map(structuralSignature),
    ]
  }
  if (node.type === 'tableRow') return [node.type, (node.content ?? []).map(structuralSignature)]
  if (node.type === 'tableCell' || node.type === 'tableHeader') {
    return [
      node.type,
      {
        sourceId: node.attrs?.sourceId,
        sourcePage: node.attrs?.sourcePage,
        sourcePath: node.attrs?.sourcePath,
        readOnly: node.attrs?.readOnly,
        lockedText: node.attrs?.lockedText,
        colspan: numericAttr(node.attrs?.colspan),
        rowspan: numericAttr(node.attrs?.rowspan),
      },
    ]
  }
  return [
    node.type,
    (node.content ?? [])
      .filter((child) => child.type === 'sourceRegion' || child.type === 'table')
      .map(structuralSignature),
  ]
}

export function validateSkeleton(expected: unknown, doc: JSONContent): string[] {
  const errors: string[] = []
  if (JSON.stringify(expected) !== JSON.stringify(structuralSignature(doc))) errors.push('Protected document structure changed.')
  const ids: string[] = []
  const visit = (node: JSONContent) => {
    if (node.attrs?.readOnly && plainText(node) !== node.attrs.lockedText) errors.push('Read-only content changed.')
    if (typeof node.attrs?.sourceId === 'string') ids.push(node.attrs.sourceId)
    node.content?.forEach(visit)
  }
  visit(doc)
  if (new Set(ids).size !== ids.length) errors.push('Duplicate source node IDs.')
  return errors
}

export function sameEditableDocument(left: JSONContent, right: JSONContent): boolean {
  return (
    JSON.stringify(structuralSignature(left)) === JSON.stringify(structuralSignature(right)) &&
    JSON.stringify([...editableTextMap(left)]) === JSON.stringify([...editableTextMap(right)])
  )
}

function currentTextAtPath(document: ReviewStateResponse['document'], path: string): string {
  const match = /^pages\[(\d+)]\.elements\[(\d+)](.*)$/.exec(path)
  if (!match) return ''
  const page = document.pages.find((item) => item.number === Number(match[1]))
  let value: Content | ElementContent | undefined = page?.elements[Number(match[2])]
  const tail = match[3]
  const segment = /\.(children|cells|titles|footers)\[(\d+)]/g
  for (const item of tail.matchAll(segment)) {
    if (!value || !('children' in value)) return ''
    value = value[item[1] as 'children' | 'cells' | 'titles' | 'footers'][Number(item[2])]
  }
  return value?.text ?? ''
}
