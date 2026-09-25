import type {
  AccessTokenProvider,
  ExportFormat,
  FindingDecisionRequest,
  OperationLookup,
  RequestedChange,
  ReviewContext,
  ReviewStateResponse,
  SaveDispatch,
  SaveReceipt,
  UpdateReviewBody,
} from './contracts'
import { isArtifactIdentity, isContextId, isUuidV4 } from './pendingSave'

export class AuthenticationRequiredError extends Error {
  constructor() {
    super('Authentication is required.')
    this.name = 'AuthenticationRequiredError'
  }
}

export class ReviewApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
  ) {
    super(code)
    this.name = 'ReviewApiError'
  }
}

export interface ReviewApi {
  load(): Promise<ReviewStateResponse>
  context(): Promise<ReviewContext>
  lookup(operationId: string, contextId: string): Promise<OperationLookup>
  save(
    expectedRevision: string | null,
    changes: RequestedChange[],
    decisions: FindingDecisionRequest[],
    dispatch?: SaveDispatch,
  ): Promise<ReviewStateResponse>
  approvePage(page: number, expectedRevision: string, contextId?: string): Promise<ReviewStateResponse>
  approve(expectedRevision: string, contextId?: string): Promise<ReviewStateResponse>
  exportUrl(revisionId: string, format: ExportFormat): Promise<string>
  fetchSource(signal: AbortSignal): Promise<Response>
}

const CONTEXT_HEADER = 'X-Review-Context'

function isInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value)
}

export function isReviewContext(value: unknown): value is ReviewContext {
  if (!value || typeof value !== 'object') return false
  const body = value as ReviewContext
  return (
    body.schema_version === 1
    && isContextId(body.context_id)
    && typeof body.job_id === 'string' && body.job_id.length > 0
    && typeof body.actor === 'string' && body.actor.length > 0
    && isArtifactIdentity(body.baseline)
  )
}

function isSaveReceipt(value: unknown): value is SaveReceipt {
  if (!value || typeof value !== 'object') return false
  const receipt = value as SaveReceipt
  return (
    isUuidV4(receipt.operation_id)
    && isUuidV4(receipt.revision_id)
    && isInteger(receipt.generation) && receipt.generation >= 1
    && typeof receipt.replayed === 'boolean'
  )
}

function isCoherentHead(headRevisionId: unknown, headGeneration: unknown): headGeneration is number {
  if (!isInteger(headGeneration) || headGeneration < 0) return false
  if (headRevisionId === null) return headGeneration === 0
  return isUuidV4(headRevisionId) && headGeneration >= 1
}

function receiptFitsHead(receipt: SaveReceipt, headRevisionId: string, headGeneration: number): boolean {
  if (receipt.generation > headGeneration) return false
  if (receipt.generation === headGeneration && receipt.revision_id !== headRevisionId) return false
  if (receipt.revision_id === headRevisionId && receipt.generation !== headGeneration) return false
  return true
}

export function isOperationLookup(value: unknown): value is OperationLookup {
  if (!value || typeof value !== 'object') return false
  const body = value as OperationLookup
  if (!isReviewContext(body.context) || !body.reconciliation || typeof body.reconciliation !== 'object') return false
  const reconciliation = body.reconciliation
  if (reconciliation.status !== 'COMMITTED' && reconciliation.status !== 'UNRESOLVED') return false
  if (!isCoherentHead(reconciliation.head_revision_id, reconciliation.head_generation)) return false
  if (reconciliation.status === 'UNRESOLVED') return reconciliation.receipt === null
  if (reconciliation.head_revision_id === null || reconciliation.head_generation < 1) return false
  if (!isSaveReceipt(reconciliation.receipt)) return false
  return receiptFitsHead(reconciliation.receipt, reconciliation.head_revision_id, reconciliation.head_generation)
}

export function isReviewState(value: unknown): value is ReviewStateResponse {
  if (!value || typeof value !== 'object') return false
  const body = value as Record<string, unknown>
  if (body.status !== 'NOT_REVIEWED' && body.status !== 'IN_REVIEW' && body.status !== 'APPROVED') return false
  if (!isInteger(body.generation) || body.generation < 0) return false
  if (body.revision_id !== null && body.revision_id !== undefined && !isUuidV4(body.revision_id)) return false
  if (!body.document || typeof body.document !== 'object') return false
  if (!body.catalogue || typeof body.catalogue !== 'object') return false
  const catalogue = body.catalogue as Record<string, unknown>
  if (!isArtifactIdentity(catalogue.baseline) || !Array.isArray(catalogue.nodes)) return false
  if (!Array.isArray(body.pages) || !Array.isArray(body.findings)) return false
  const document = body.document as Record<string, unknown>
  if (!Array.isArray(document.pages)) return false
  if (body.generation >= 1 && (typeof body.revision_id !== 'string' || !isUuidV4(body.revision_id))) return false
  if ((body.status === 'IN_REVIEW' || body.status === 'APPROVED') && (body.generation < 1 || !isUuidV4(body.revision_id))) {
    return false
  }
  return true
}

export function isConfirmedSaveState(value: unknown): value is ReviewStateResponse {
  if (!isReviewState(value)) return false
  if (value.status === 'NOT_REVIEWED' || value.revision_id === null || value.revision_id === undefined) return false
  if (value.generation < 1) return false
  return true
}

export function createReviewApi(
  jobId: string,
  getAccessToken: AccessTokenProvider,
  onAuthenticationRequired: () => void,
  apiBaseUrl = '',
): ReviewApi {
  const root = `${apiBaseUrl.replace(/\/$/, '')}/api/v1/documents/jobs/${encodeURIComponent(jobId)}`

  async function authHeaders(): Promise<Record<string, string>> {
    const token = await getAccessToken()
    return token ? { Authorization: `Bearer ${token}` } : {}
  }

  async function rawRequest(path: string, init: RequestInit = {}): Promise<Response> {
    const response = await fetch(`${root}${path}`, {
      ...init,
      cache: 'no-store',
      headers: {
        Accept: 'application/json',
        'Cache-Control': 'no-store',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...(await authHeaders()),
        ...init.headers,
      },
    })
    if (response.status === 401) {
      onAuthenticationRequired()
      throw new AuthenticationRequiredError()
    }
    if (!response.ok) {
      let code = `HTTP_${response.status}`
      try {
        const body: unknown = await response.json()
        if (body && typeof body === 'object' && 'code' in body && typeof body.code === 'string') code = body.code
      } catch {
        // Error responses are intentionally reduced to safe codes.
      }
      throw new ReviewApiError(code, response.status)
    }
    return response
  }

  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await rawRequest(path, init)
    try {
      return (await response.json()) as T
    } catch {
      throw new ReviewApiError('INVALID_RESPONSE', 502)
    }
  }

  async function requestState(path: string, init: RequestInit = {}): Promise<ReviewStateResponse> {
    const body: unknown = await request<unknown>(path, init)
    if (!isReviewState(body)) throw new ReviewApiError('INVALID_RESPONSE', 502)
    return body
  }

  const contextHeaders = (contextId?: string): Record<string, string> =>
    contextId ? { [CONTEXT_HEADER]: contextId } : {}

  const update = (body: string | UpdateReviewBody, contextId?: string) =>
    requestState('/review', {
      method: 'PUT',
      body: typeof body === 'string' ? body : JSON.stringify(body),
      headers: contextHeaders(contextId),
    })

  const revisionAction = (path: string, expectedRevision: string, contextId?: string) =>
    requestState(path, {
      method: 'POST',
      body: JSON.stringify({ expected_revision: expectedRevision }),
      headers: contextHeaders(contextId),
    })

  return {
    load: () => requestState('/review'),
    async context() {
      const body: unknown = await request<unknown>('/review/context')
      if (!isReviewContext(body)) throw new ReviewApiError('INVALID_RESPONSE', 502)
      return body
    },
    async lookup(operationId, contextId) {
      const body: unknown = await request<unknown>(`/review/operations/${encodeURIComponent(operationId)}`, {
        headers: contextHeaders(contextId),
      })
      if (!isOperationLookup(body)) throw new ReviewApiError('INVALID_RESPONSE', 502)
      if (body.context.context_id !== contextId) throw new ReviewApiError('REVIEW_CONTEXT_CHANGED', 409)
      if (body.reconciliation.receipt && body.reconciliation.receipt.operation_id !== operationId) {
        throw new ReviewApiError('INVALID_RESPONSE', 502)
      }
      return body
    },
    save: (expected_revision, changes, decisions, dispatch) =>
      update(
        dispatch?.body ?? { expected_revision, changes, decisions },
        dispatch?.contextId,
      ),
    approvePage: (page, revision, contextId) =>
      revisionAction(`/review/pages/${page}/approve`, revision, contextId),
    approve: (revision, contextId) => revisionAction('/review/approve', revision, contextId),
    async exportUrl(revisionId, format) {
      const { url } = await request<{ url: string }>(
        `/review/revisions/${encodeURIComponent(revisionId)}/exports/${format}`,
      )
      return url
    },
    async fetchSource(signal) {
      return rawRequest('/source', { signal, headers: { Accept: 'application/pdf' } })
    },
  }
}
