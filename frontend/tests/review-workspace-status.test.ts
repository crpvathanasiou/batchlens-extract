import { type App } from 'vue'
import { createApp } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReviewApi } from '../src/api'
import type { ReviewStateResponse, ReviewWorkspaceOptions } from '../src/contracts'
import { reviewFixture, toleranceReviewFixture } from './fixture'

vi.mock('../src/components/PdfPane.vue', () => ({
  default: {
    name: 'PdfPane',
    props: ['api', 'page', 'expectedPageCount'],
    emits: ['page-count', 'mismatch'],
    template: '<div class="pdf-stub" />',
  },
}))

vi.mock('../src/components/DocumentEditor.vue', () => ({
  default: {
    name: 'DocumentEditor',
    props: ['content', 'disabled', 'toleranceNodeIds'],
    emits: ['update', 'content-error'],
    template: '<div class="editor-stub" :data-tolerance-ids="(toleranceNodeIds || []).join(\',\')" />',
  },
}))

const apiState = vi.hoisted(() => ({
  server: null as ReviewStateResponse | null,
}))

vi.mock('../src/api', async () => {
  const actual = await vi.importActual<typeof import('../src/api')>('../src/api')
  return {
    ...actual,
    createReviewApi: (): ReviewApi => ({
      load: vi.fn(async () => apiState.server!),
      save: vi.fn(async () => apiState.server!),
      approvePage: vi.fn(async () => apiState.server!),
      approve: vi.fn(async () => apiState.server!),
      exportUrl: vi.fn(async () => '/export'),
      fetchSource: vi.fn(),
    }),
  }
})

import ReviewWorkspace from '../src/components/ReviewWorkspace.vue'

const mounts: Array<{ app: App; host: HTMLElement }> = []

async function mountWorkspace(server: ReviewStateResponse) {
  apiState.server = server
  const host = document.createElement('div')
  document.body.appendChild(host)
  const options: ReviewWorkspaceOptions = {
    jobId: 'job-1',
    filename: 'sample.pdf',
    getAccessToken: async () => 'token',
    onAuthenticationRequired: () => undefined,
  }
  const app = createApp(ReviewWorkspace, { options })
  app.mount(host)
  await vi.waitFor(() => {
    expect(host.querySelector('.bl-chip--document-status')).not.toBeNull()
  })
  mounts.push({ app, host })
  return host
}

afterEach(() => {
  while (mounts.length) {
    const mounted = mounts.pop()
    mounted?.app.unmount()
    mounted?.host.remove()
  }
})

describe('ReviewWorkspace document status', () => {
  it.each([
    ['NOT_REVIEWED', 'Document status · Not reviewed'],
    ['IN_REVIEW', 'Document status · In review'],
    ['APPROVED', 'Document status · Approved'],
  ] as const)('renders Document status with %s', async (status, label) => {
    const host = await mountWorkspace({ ...reviewFixture(), status })
    const chip = host.querySelector('.bl-chip--document-status')
    expect(chip?.textContent?.replace(/\s+/g, ' ').trim()).toBe(label)
    expect(chip?.textContent).toContain('Document status')
    expect(host.querySelectorAll('.bl-statuses .bl-chip')).toHaveLength(2)
  })
})

describe('ReviewWorkspace tolerance marker ids', () => {
  it('passes unresolved tolerance node ids to the editor', async () => {
    const host = await mountWorkspace(toleranceReviewFixture())
    expect(host.querySelector('.editor-stub')?.getAttribute('data-tolerance-ids')).toBe('n-cell-3')
  })

  it('does not pass resolved or non-tolerance findings', async () => {
    const server = toleranceReviewFixture()
    server.findings = [
      {
        ...server.findings[0],
        decision: {
          action: 'KEEP_ORIGINAL',
          note: null,
          actor: 'reviewer',
          at: '2026-01-01T00:00:00Z',
          revision_id: 'revision-1',
          region_hash: 'region-hash-tol',
        },
      },
      {
        ...server.findings[0],
        finding_id: 'figure',
        code: 'UNINTERPRETED_LAYOUT_FIGURE',
        node_ids: ['n-parent'],
        decision: null,
        suggested_replacement: null,
      },
    ]
    const host = await mountWorkspace(server)
    expect(host.querySelector('.editor-stub')?.getAttribute('data-tolerance-ids')).toBe('')
  })
})
