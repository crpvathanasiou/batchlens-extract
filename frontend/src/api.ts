import type {
  AccessTokenProvider,
  ExportFormat,
  FindingDecisionRequest,
  RequestedChange,
  ReviewStateResponse,
  UpdateReviewBody,
} from './contracts'

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
  save(expectedRevision: string | null, changes: RequestedChange[], decisions: FindingDecisionRequest[]): Promise<ReviewStateResponse>
  approvePage(page: number, expectedRevision: string): Promise<ReviewStateResponse>
  approve(expectedRevision: string): Promise<ReviewStateResponse>
  exportUrl(revisionId: string, format: ExportFormat): Promise<string>
  fetchSource(signal: AbortSignal): Promise<Response>
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

  const update = (body: UpdateReviewBody) =>
    request<ReviewStateResponse>('/review', {
      method: 'PUT',
      body: JSON.stringify(body),
    })

  const revisionAction = (path: string, expectedRevision: string) =>
    request<ReviewStateResponse>(path, {
      method: 'POST',
      body: JSON.stringify({ expected_revision: expectedRevision }),
    })

  return {
    load: () => request<ReviewStateResponse>('/review'),
    save: (expected_revision, changes, decisions) => update({ expected_revision, changes, decisions }),
    approvePage: (page, revision) => revisionAction(`/review/pages/${page}/approve`, revision),
    approve: (revision) => revisionAction('/review/approve', revision),
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
