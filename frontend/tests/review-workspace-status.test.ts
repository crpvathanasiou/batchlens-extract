import { type App } from 'vue'
import { createApp } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReviewApi } from '../src/api'
import type { ReviewStateResponse, ReviewWorkspaceOptions } from '../src/contracts'
import { reviewFixture, toleranceReviewFixture, inReviewState, FIXTURE_REVISION_1 } from './fixture'
import { pendingSaveKey, pendingSaveScope, serializeSaveBody } from '../src/pendingSave'

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
      context: vi.fn(async () => ({
        schema_version: 1 as const,
        context_id: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        job_id: 'job-1',
        actor: 'alice',
        baseline: apiState.server!.catalogue.baseline,
      })),
      lookup: vi.fn(async () => ({
        context: {
          schema_version: 1 as const,
          context_id: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
          job_id: 'job-1',
          actor: 'alice',
          baseline: apiState.server!.catalogue.baseline,
        },
        reconciliation: { status: 'UNRESOLVED' as const, head_revision_id: null, head_generation: 0, receipt: null },
      })),
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
  sessionStorage.clear()
})

describe('ReviewWorkspace document status', () => {
  it.each([
    ['NOT_REVIEWED', 'Document status · Not reviewed', reviewFixture()],
    ['IN_REVIEW', 'Document status · In review', inReviewState(reviewFixture(), FIXTURE_REVISION_1, 1)],
    ['APPROVED', 'Document status · Approved', { ...inReviewState(reviewFixture(), FIXTURE_REVISION_1, 1), status: 'APPROVED' as const }],
  ] as const)('renders Document status with %s', async (status, label, server) => {
    const host = await mountWorkspace(server)
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

describe('ReviewWorkspace recovery presentation', () => {
  it('shows attempted text and finding decisions and hides discard without terminal evidence', async () => {
    const server = toleranceReviewFixture()
    const contextId = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    sessionStorage.setItem(pendingSaveKey(pendingSaveScope(''), contextId), JSON.stringify({
      schema_version: 1,
      context_id: contextId,
      job_id: 'job-1',
      actor: 'alice',
      baseline: server.catalogue.baseline,
      operation_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      body: serializeSaveBody(
        null,
        [{ node_id: 'n-parent', text: 'manual-attempt\n' }],
        [
          { finding_id: 'finding-tol', action: 'RESOLVED_AFTER_EDIT', replacement: { node_id: 'n-cell-3', text: 'Tolerance ±0.1%' }, note: 'check source' },
          { finding_id: 'finding-keep', action: 'KEEP_ORIGINAL' },
          { finding_id: 'finding-limit', action: 'ACKNOWLEDGED_LIMITATION', note: 'known limitation' },
        ],
        'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      ),
      expected_revision: null,
      base_generation: 0,
      phase: 'uncertain',
      ambiguous: true,
      message: null,
    }))
    const host = await mountWorkspace(server)
    const attempted = host.querySelector('.bl-attempted')?.textContent ?? ''
    expect(attempted).toContain('manual-attempt')
    expect(attempted).toContain('Keep original')
    expect(attempted).toContain('Mark resolved after edit')
    expect(attempted).toContain('Acknowledge limitation')
    expect(attempted).toContain('Suggested replacement: Tolerance ±0.1%')
    expect(attempted).toContain('Note: check source')
    const labels = [...host.querySelectorAll('.bl-recovery-actions button')].map((button) => button.textContent?.trim())
    expect(labels).toContain('Check save status')
    expect(labels).toContain('Retry same save')
    expect(labels).not.toContain('Discard attempted save')
  })
})
