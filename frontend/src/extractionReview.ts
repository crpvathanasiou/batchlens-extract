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
  }
}
