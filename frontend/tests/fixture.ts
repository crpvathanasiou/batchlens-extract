import type { CatalogueNode, Content, ReviewFinding, ReviewStateResponse } from '../src/contracts'

const content = (text: string): Content => ({ text, references: [], selections: [] })
const geometry = (
  rows: number,
  columns: number,
  row: number | null = null,
  column: number | null = null,
  row_span: number | null = null,
  column_span: number | null = null,
  header: boolean | null = null,
) => ({ rows, columns, row, column, row_span, column_span, header })

const emptyElement = {
  children: [] as never[],
  cells: [] as never[],
  titles: [] as never[],
  footers: [] as never[],
  rows: 0,
  columns: 0,
}

export function reviewFixture(): ReviewStateResponse {
  const table = {
    ...content('Parent\n'),
    kind: 'TABLE',
    children: [{
      ...content('Child\n\n'),
      kind: 'TEXT',
      ...emptyElement,
    }],
    cells: [
      { ...content(''), row: 1, column: 1, row_span: 2, column_span: 1, header: true, entity_types: [], inferred_empty: false },
      { ...content('A\nB'), row: 1, column: 2, row_span: 1, column_span: 2, header: true, entity_types: [], inferred_empty: false },
      { ...content('C'), row: 2, column: 2, row_span: 1, column_span: 1, header: false, entity_types: [], inferred_empty: false },
      { ...content(''), row: 2, column: 3, row_span: 1, column_span: 1, header: false, entity_types: [], inferred_empty: true },
    ],
    titles: [content('Title')],
    footers: [content('Footer\n')],
    rows: 2,
    columns: 3,
  }
  const paths = [
    ['n-parent', 'pages[1].elements[0]', 'TABLE', 'Parent\n', geometry(2, 3)],
    ['n-child', 'pages[1].elements[0].children[0]', 'TEXT', 'Child\n\n', null],
    ['n-cell-1', 'pages[1].elements[0].cells[0]', 'TABLE_CELL', '', geometry(2, 3, 1, 1, 2, 1, true)],
    ['n-cell-2', 'pages[1].elements[0].cells[1]', 'TABLE_CELL', 'A\nB', geometry(2, 3, 1, 2, 1, 2, true)],
    ['n-cell-3', 'pages[1].elements[0].cells[2]', 'TABLE_CELL', 'C', geometry(2, 3, 2, 2, 1, 1, false)],
    ['n-cell-4', 'pages[1].elements[0].cells[3]', 'TABLE_CELL', '', geometry(2, 3, 2, 3, 1, 1, false)],
    ['n-title', 'pages[1].elements[0].titles[0]', 'TITLE', 'Title', null],
    ['n-footer', 'pages[1].elements[0].footers[0]', 'FOOTER', 'Footer\n', null],
    ['n-doc-title', 'pages[1].elements[1]', 'title', 'Canonical title', null],
    ['n-section', 'pages[1].elements[2]', 'section_heading', 'Canonical section', null],
    ['n-page-2', 'pages[2].elements[0]', 'TEXT', 'Second page', null],
    ['n-page-2-table', 'pages[2].elements[1]', 'TABLE', 'Page two table\n', geometry(1, 2)],
    ['n-page-2-cell-1', 'pages[2].elements[1].cells[0]', 'TABLE_CELL', 'P2A', geometry(1, 2, 1, 1, 1, 1, true)],
    ['n-page-2-cell-2', 'pages[2].elements[1].cells[1]', 'TABLE_CELL', 'P2B', geometry(1, 2, 1, 2, 1, 1, false)],
  ] as const
  const nodes: CatalogueNode[] = paths.map(([node_id, path, kind, baseline_text, table_geometry]) => ({
    node_id,
    page_number: path.startsWith('pages[2]') ? 2 : 1,
    path,
    kind,
    baseline_text,
    baseline_hash: `hash-${node_id}`,
    reference_ids: [],
    references: [],
    table_geometry,
  }))
  return {
    status: 'NOT_REVIEWED',
    revision_id: null,
    generation: 0,
    revision: null,
    source_page_count: 2,
    document: {
      schema_version: '1.0.0',
      converter_version: '1.0.0',
      source: { identity: 'source' },
      status: 'SUCCEEDED',
      provider_model_version: null,
      declared_pages: 2,
      pages: [
        {
          number: 1,
          reading_order: 'textract_layout',
          elements: [
            table,
            { ...content('Canonical title'), kind: 'title', ...emptyElement },
            { ...content('Canonical section'), kind: 'section_heading', ...emptyElement },
          ],
        },
        {
          number: 2,
          reading_order: 'textract_layout',
          elements: [
            { ...content('Second page'), kind: 'TEXT', ...emptyElement },
            {
              ...content('Page two table\n'),
              kind: 'TABLE',
              children: [],
              cells: [
                { ...content('P2A'), row: 1, column: 1, row_span: 1, column_span: 1, header: true, entity_types: [], inferred_empty: false },
                { ...content('P2B'), row: 1, column: 2, row_span: 1, column_span: 1, header: false, entity_types: [], inferred_empty: false },
              ],
              titles: [],
              footers: [],
              rows: 1,
              columns: 2,
            },
          ],
        },
      ],
      warnings: [],
    },
    catalogue: {
      baseline: { key: 'document.json', version: '1', content_type: 'application/json' },
      nodes,
      catalogue_hash: 'catalogue-hash',
    },
    pages: [
      { page_number: 1, content_hash: 'page-1', approval: null },
      { page_number: 2, content_hash: 'page-2', approval: null },
    ],
    findings: [],
  }
}

export function toleranceReviewFixture(): ReviewStateResponse {
  const server = reviewFixture()
  const document = structuredClone(server.document)
  document.pages[0].elements[0].cells[2].text = 'Toler +0.1%'
  const findings: ReviewFinding[] = [{
    finding_id: 'finding-tol',
    code: 'POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY',
    pages: [1],
    block_ids: ['b1'],
    node_ids: ['n-cell-3'],
    evidence: [],
    region_hash: 'region-hash-tol',
    decision: null,
    suggested_replacement: {
      eligible: true,
      node_id: 'n-cell-3',
      text: 'Tolerance ±0.1%',
      expected_region_hash: 'region-hash-tol',
    },
  }]
  return {
    ...server,
    document,
    catalogue: {
      ...server.catalogue,
      nodes: server.catalogue.nodes.map((node) =>
        node.node_id === 'n-cell-3' ? { ...node, baseline_text: 'Toler +0.1%' } : node,
      ),
    },
    findings,
  }
}
