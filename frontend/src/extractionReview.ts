export interface ExtractionJobSummary {
  local_job_id: string
  job_id: string
  review_revision_id: string
  action: string
  extraction_overall: string
  finished_at: string | null
}

export interface ExtractionFinding {
  finding_id: string
  component: string | null
  display_text: string | null
  page_number: number | null
  evidence_status: string | null
  removed: boolean
  origin_kind: 'lexical' | 'user_added'
  block_node_id: string | null
  start_char: number | null
  end_char: number | null
  original_matched_text: string | null
  added_by_user: boolean
  changed_by_user: boolean
  removed_by_user: boolean
}

export interface ClassificationEvidenceItem {
  label: string
  quote: string | null
  reason: string | null
  element_id: string | null
  evidence_verification: string | null
  evidence_verification_reason: string | null
  provenance?: string | null
}

export interface PageClassificationView {
  page_number: number
  kind: string
  requires_review: boolean
  is_provisional: boolean
  applied_other_unclassified: boolean
  labels: ClassificationEvidenceItem[]
  evidence: ClassificationEvidenceItem[]
  source_validation: {
    has_unverified: boolean
    requires_review: boolean
    items: ClassificationEvidenceItem[]
  }
  eligibility: {
    eligible_for_extraction: boolean
    reason: string
    excluded_by_policy: boolean
  }
}

export interface ClassificationStateView {
  job_id: string
  review_revision_id: string
  status: string
  progress: {
    total_pages: number
    completed_pages: number
    current_page_number: number | null
  }
  created_at: string
  updated_at: string
  finished_at: string | null
  terminal_reason: string | null
  pages: PageClassificationView[]
  source: 'current' | 'job_snapshot'
}

export interface ApprovedDocumentSummary {
  job_id: string
  review_revision_id: string
}

export interface LexicalJobStatus {
  local_job_id: string
  job_id: string
  review_revision_id: string
  status: string
  phase: string
  action: string
  submitted_at: string
  started_at: string | null
  finished_at: string | null
  error_code: string | null
  error_message: string | null
  classified: boolean
  selected_page_numbers: number[] | null
  extraction_overall: string | null
  reviewable: boolean
}

export type ExtractAllResult =
  | { kind: 'submitted'; job: LexicalJobStatus }
  | { kind: 'no_eligible_pages'; message: string }

export interface OpenedExtractionReview {
  local_job_id: string
  job_id: string
  review_revision_id: string
  action: string
  extraction_overall: string
  current_revision_id: string
  approval_state: 'not_approved' | 'approved'
  pages: number[]
  findings: ExtractionFinding[]
  classification?: ClassificationStateView | null
}

export interface ExtractionReviewOptions {
  apiBaseUrl?: string
  demoLabel?: string
  /** When set and present in the jobs list, open this job first (harness --run-extraction). */
  initialLocalJobId?: string
}

export type PageEdit =
  | {
      op: 'add'
      finding_id: string
      page_number: number
      component: string
      display_text: string
    }
  | {
      op: 'patch_text'
      finding_id: string
      page_number: number
      display_text: string
    }
  | {
      op: 'replace'
      finding_id: string
      page_number: number
      component: string
      display_text: string
    }
  | {
      op: 'remove'
      finding_id: string
      page_number: number
    }
  | {
      op: 'restore'
      finding_id: string
      page_number: number
    }

export const STAGE4_POLL_INTERVAL_MS = 1000

export function isTerminalClassificationStatus(status: string | null | undefined): boolean {
  return status === 'completed' || status === 'failed' || status === 'interrupted'
}

export function isTerminalLexicalStatus(status: string | null | undefined): boolean {
  return status === 'completed' || status === 'failed' || status === 'interrupted'
}

/** Strip tabs/newlines so each TSV cell stays on one line. */
export function sanitizeClassificationTsvValue(value: string): string {
  return value.replace(/[\t\r\n]+/g, ' ').replace(/ +/g, ' ').trim()
}

function classificationStateMarkers(page: PageClassificationView): string[] {
  const markers: string[] = []
  if (page.kind === 'incomplete') markers.push('incomplete')
  if (
    page.kind === 'needs_review'
    || page.requires_review
    || page.source_validation.requires_review
  ) {
    markers.push('needs_review')
  }
  if (page.kind === 'empty') markers.push('empty')
  if (page.is_provisional) markers.push('provisional')
  if (page.source_validation.has_unverified) markers.push('unverified_evidence')
  return [...new Set(markers)]
}

/** Second-column value for one page in the classifications TXT export. */
export function formatPageClassificationColumn(page: PageClassificationView | null | undefined): string {
  if (!page) return '[no completed classification result]'
  const labels = page.labels
    .map((item) => sanitizeClassificationTsvValue(item.label))
    .filter((label) => label.length > 0)
  if (labels.length === 0 && page.applied_other_unclassified) {
    labels.push('OTHER_UNCLASSIFIED')
  }
  const markers = classificationStateMarkers(page)
  const labelPart = labels.join('; ')
  if (markers.length === 0) {
    return labelPart.length > 0 ? labelPart : '[no completed classification result]'
  }
  const markerPart = `[${markers.join('; ')}]`
  return labelPart.length > 0 ? `${labelPart} ${markerPart}` : markerPart
}

/** UTF-8 TSV body: Page number / Page classification, one row per page in order. */
export function buildPageClassificationsTsv(
  pageNumbers: readonly number[],
  classification: ClassificationStateView,
): string {
  const byPage = new Map(classification.pages.map((page) => [page.page_number, page]))
  const lines = ['Page number\tPage classification']
  for (const pageNumber of pageNumbers) {
    const cell = sanitizeClassificationTsvValue(
      formatPageClassificationColumn(byPage.get(pageNumber)),
    )
    lines.push(`${pageNumber}\t${cell}`)
  }
  return `${lines.join('\n')}\n`
}

export function pageClassificationsDownloadFilename(input: {
  source: 'current' | 'job_snapshot'
  jobId: string
  reviewRevisionId: string
  localJobId?: string | null
}): string {
  const safe = (value: string) => value.replace(/[^A-Za-z0-9._-]+/g, '_')
  if (input.source === 'job_snapshot' && input.localJobId) {
    return `page-classifications-job-snapshot-${safe(input.localJobId)}.txt`
  }
  return `page-classifications-current-${safe(input.jobId)}-${safe(input.reviewRevisionId)}.txt`
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { cache: 'no-store', ...init })
  const payload = (await response.json()) as T & { message?: string; code?: string }
  if (!response.ok) {
    throw new Error(payload.message || payload.code || 'Extraction review request failed')
  }
  return payload
}

export function createExtractionReviewApi(apiBaseUrl = '') {
  const root = `${apiBaseUrl}/api/v1/extraction-reviews`
  return {
    listJobs(): Promise<{ jobs: ExtractionJobSummary[] }> {
      return requestJson(`${root}/jobs`)
    },
    openJob(localJobId: string): Promise<OpenedExtractionReview> {
      return requestJson(`${root}/jobs/${encodeURIComponent(localJobId)}`)
    },
    page(localJobId: string, pageNumber: number): Promise<{ page_number: number; html: string }> {
      return requestJson(`${root}/jobs/${encodeURIComponent(localJobId)}/pages/${pageNumber}`)
    },
    save(localJobId: string, expectedRevisionId: string, edits: PageEdit[]): Promise<OpenedExtractionReview> {
      return requestJson(`${root}/jobs/${encodeURIComponent(localJobId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_revision_id: expectedRevisionId, edits }),
      })
    },
    approve(localJobId: string, expectedRevisionId: string): Promise<OpenedExtractionReview> {
      return requestJson(`${root}/jobs/${encodeURIComponent(localJobId)}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_revision_id: expectedRevisionId }),
      })
    },
    resultsTxtUrl(localJobId: string): string {
      return `${root}/jobs/${encodeURIComponent(localJobId)}/results.txt`
    },
    listApprovedDocuments(): Promise<{ documents: ApprovedDocumentSummary[] }> {
      return requestJson(`${root}/approved-documents`)
    },
    approvedDocumentPages(
      jobId: string,
      reviewRevisionId: string,
    ): Promise<{ job_id: string; review_revision_id: string; pages: number[] }> {
      return requestJson(
        `${root}/approved-documents/${encodeURIComponent(jobId)}/${encodeURIComponent(reviewRevisionId)}/pages`,
      )
    },
    approvedDocumentPage(
      jobId: string,
      reviewRevisionId: string,
      pageNumber: number,
    ): Promise<{ page_number: number; html: string }> {
      return requestJson(
        `${root}/approved-documents/${encodeURIComponent(jobId)}/${encodeURIComponent(reviewRevisionId)}/pages/${pageNumber}`,
      )
    },
    getClassification(
      jobId: string,
      reviewRevisionId: string,
    ): Promise<{ classification: ClassificationStateView | null }> {
      return requestJson(
        `${root}/approved-documents/${encodeURIComponent(jobId)}/${encodeURIComponent(reviewRevisionId)}/classification`,
      )
    },
    startClassification(
      jobId: string,
      reviewRevisionId: string,
    ): Promise<{ classification: ClassificationStateView | null }> {
      return requestJson(
        `${root}/approved-documents/${encodeURIComponent(jobId)}/${encodeURIComponent(reviewRevisionId)}/classify`,
        { method: 'POST' },
      )
    },
    extractAll(jobId: string, reviewRevisionId: string): Promise<ExtractAllResult> {
      return requestJson(
        `${root}/approved-documents/${encodeURIComponent(jobId)}/${encodeURIComponent(reviewRevisionId)}/extract-all`,
        { method: 'POST' },
      )
    },
    localJobStatus(localJobId: string): Promise<LexicalJobStatus> {
      return requestJson(`${root}/local-jobs/${encodeURIComponent(localJobId)}`)
    },
    jobClassification(
      localJobId: string,
    ): Promise<{ classification: ClassificationStateView | null }> {
      return requestJson(`${root}/jobs/${encodeURIComponent(localJobId)}/classification`)
    },
  }
}
