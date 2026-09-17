export type ReviewStatus = 'NOT_REVIEWED' | 'IN_REVIEW' | 'APPROVED'
export type DecisionAction = 'KEEP_ORIGINAL' | 'RESOLVED_AFTER_EDIT' | 'ACKNOWLEDGED_LIMITATION'
export type ExportFormat = 'html' | 'json'

export interface Artifact {
  key: string
  version: string
  content_type: string
}
export interface Reference {
  block_id: string
  page: number | null
  box?: { left: number; top: number; width: number; height: number } | null
  polygon?: { x: number; y: number }[]
  confidence?: number | null
  rotation_angle?: number | null
}
export interface Content {
  text: string
  references: Reference[]
  selections: ('SELECTED' | 'NOT_SELECTED')[]
}
export interface Cell extends Content {
  row: number
  column: number
  row_span: number
  column_span: number
  header: boolean
  entity_types: string[]
  inferred_empty: boolean
}
export interface ElementContent extends Content {
  kind: string
  children: ElementContent[]
  cells: Cell[]
  titles: Content[]
  footers: Content[]
  rows: number
  columns: number
}
export interface CanonicalPage {
  number: number
  elements: ElementContent[]
  reading_order: 'textract_layout' | 'geometry_fallback'
}
export interface CanonicalDocument {
  schema_version: string
  converter_version: string
  source: Record<string, unknown>
  status: 'SUCCEEDED' | 'PARTIAL_SUCCESS'
  provider_model_version: string | null
  declared_pages: number | null
  pages: CanonicalPage[]
  warnings: { code: string; block_ids: string[]; pages: number[] }[]
}
export interface TableGeometry {
  rows: number
  columns: number
  row: number | null
  column: number | null
  row_span: number | null
  column_span: number | null
  header: boolean | null
}
export interface CatalogueNode {
  node_id: string
  page_number: number
  path: string
  kind: string
  baseline_text: string
  baseline_hash: string
  reference_ids: string[]
  references: Reference[]
  table_geometry: TableGeometry | null
}
export interface ReviewCatalogue {
  baseline: Artifact
  nodes: CatalogueNode[]
  catalogue_hash: string
}
export interface FindingDecision {
  action: DecisionAction
  note: string | null
  actor: string
  at: string
  revision_id: string
  region_hash: string
}
export interface ReviewFinding {
  finding_id: string
  code: string
  pages: number[]
  block_ids: string[]
  node_ids: string[]
  evidence: Reference[]
  region_hash: string
  decision: FindingDecision | null
  suggested_replacement?: {
    eligible: boolean
    node_id: string
    text: string
    expected_region_hash: string
  } | null
}
export interface PageApproval {
  content_hash: string
  actor: string
  at: string
  revision_id: string
}
export interface PageState {
  page_number: number
  content_hash: string
  approval: PageApproval | null
}
export interface ExportPointers {
  html_artifact: Artifact
  json_artifact: Artifact
}
export interface S3Source {
  bucket: string
  key: string
  region: string
  version: string | null
  checksum_sha256: string | null
  etag: string | null
}
export interface TextChange {
  node_id: string
  baseline: Artifact
  original_text: string
  previous_text: string
  new_text: string
  actor: string
  at: string
  revision_id: string
}
export interface ReviewRevision {
  schema_version: string
  job_id: string
  owner: string
  revision_id: string
  parent_revision_id: string | null
  parent: Artifact | null
  generation: number
  created_at: string
  actor: string
  baseline: Artifact
  accepted_source: S3Source
  raw: Artifact
  document: CanonicalDocument
  catalogue: ReviewCatalogue
  pages: PageState[]
  findings: ReviewFinding[]
  changes: TextChange[]
  action: 'DRAFT_SAVED' | 'PAGE_APPROVED' | 'DOCUMENT_APPROVED'
  exports: ExportPointers | null
  document_approval: { revision_id: string; document_hash: string; actor: string; at: string } | null
}
export interface ReviewStateResponse {
  status: ReviewStatus
  revision_id: string | null
  generation: number
  revision: ReviewRevision | null
  document: CanonicalDocument
  catalogue: ReviewCatalogue
  pages: PageState[]
  findings: ReviewFinding[]
  source_page_count?: number
}
export interface RequestedChange {
  node_id: string
  text: string
}
export interface FindingDecisionRequest {
  finding_id: string
  action: DecisionAction
  note?: string | null
  replacement?: RequestedChange | null
  expected_region_hash?: string | null
}
export interface UpdateReviewBody {
  expected_revision: string | null
  changes: RequestedChange[]
  decisions: FindingDecisionRequest[]
}
export type AccessTokenProvider = () => string | null | Promise<string | null>
export interface ReviewWorkspaceOptions {
  jobId: string
  filename: string
  getAccessToken: AccessTokenProvider
  onAuthenticationRequired: () => void
  onDirtyChange?: (dirty: boolean) => void
  onBack?: () => void
  apiBaseUrl?: string
  demoLabel?: string
}
