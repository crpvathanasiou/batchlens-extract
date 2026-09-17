import { nextTick, ref, type App } from 'vue'
import { createApp } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import type { JSONContent } from '@tiptap/core'
import type { ReviewFinding } from '../src/contracts'
import { TOLERANCE_MARKER_TITLE } from '../src/extensions'
import { projectPage } from '../src/mapping'
import { unresolvedToleranceNodeIds } from '../src/state'
import DocumentEditor from '../src/components/DocumentEditor.vue'
import { toleranceReviewFixture } from './fixture'

function recorded(action: 'KEEP_ORIGINAL' = 'KEEP_ORIGINAL') {
  return {
    action,
    note: null,
    actor: 'reviewer',
    at: '2026-01-01T00:00:00Z',
    revision_id: 'revision-1',
    region_hash: 'region-hash-tol',
  } as const
}

function finding(overrides: Partial<ReviewFinding> = {}): ReviewFinding {
  return { ...toleranceReviewFixture().findings[0], ...overrides }
}

describe('unresolvedToleranceNodeIds', () => {
  it('passes mapped node ids for an unresolved tolerance finding', () => {
    expect(unresolvedToleranceNodeIds(toleranceReviewFixture().findings)).toEqual(['n-cell-3'])
  })

  it('does not mark a recorded resolved tolerance finding', () => {
    expect(unresolvedToleranceNodeIds([finding({ decision: recorded() })])).toEqual([])
  })

  it('does not mark a non-tolerance finding', () => {
    expect(
      unresolvedToleranceNodeIds([
        finding({
          finding_id: 'figure',
          code: 'UNINTERPRETED_LAYOUT_FIGURE',
          node_ids: ['n-parent'],
        }),
      ]),
    ).toEqual([])
  })
})

describe('DocumentEditor tolerance marker', () => {
  const mounts: Array<{ app: App; host: HTMLElement }> = []

  async function mountEditor(nodeIds: string[]) {
    const page = ref(projectPage(toleranceReviewFixture(), 1).doc as JSONContent)
    const host = document.createElement('div')
    document.body.appendChild(host)
    const app = createApp({
      components: { DocumentEditor },
      setup: () => ({ page, nodeIds }),
      template: '<DocumentEditor :content="page" :tolerance-node-ids="nodeIds" />',
    })
    app.mount(host)
    await nextTick()
    await nextTick()
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

  it('decorates the mapped cell without changing extracted text', async () => {
    const host = await mountEditor(['n-cell-3'])
    const cell = host.querySelector('[data-source-cell="n-cell-3"]')
    expect(cell).not.toBeNull()
    expect(cell?.classList.contains('bl-tolerance-warning')).toBe(true)
    expect(cell?.getAttribute('title')).toBe(TOLERANCE_MARKER_TITLE)
    expect(cell?.textContent).toContain('Toler +0.1%')
    expect(host.querySelector('[data-source-cell="n-cell-2"]')?.classList.contains('bl-tolerance-warning')).toBe(false)
  })

  it('does not decorate when no unresolved tolerance node ids are supplied', async () => {
    const host = await mountEditor([])
    expect(host.querySelector('.bl-tolerance-warning')).toBeNull()
  })
})
