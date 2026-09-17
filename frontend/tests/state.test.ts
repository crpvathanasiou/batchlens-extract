import type { JSONContent } from '@tiptap/core'
import { describe, expect, it, vi } from 'vitest'
import { AuthenticationRequiredError, ReviewApiError, type ReviewApi } from '../src/api'
import { createReviewState } from '../src/state'
import { reviewFixture, toleranceReviewFixture } from './fixture'

function fakeApi(saveError?: Error, server = reviewFixture()): ReviewApi {
  return {
    load: vi.fn().mockResolvedValue(server),
    save: saveError
      ? vi.fn().mockRejectedValue(saveError)
      : vi.fn().mockResolvedValue({ ...server, status: 'IN_REVIEW', revision_id: 'revision-1' }),
    approvePage: vi.fn().mockResolvedValue(server),
    approve: vi.fn().mockResolvedValue({ ...server, status: 'APPROVED', revision_id: 'revision-2' }),
    exportUrl: vi.fn().mockResolvedValue('/export'),
    fetchSource: vi.fn(),
  }
}

describe('review state', () => {
  it('keeps an in-memory draft when authentication interrupts saving', async () => {
    const state = createReviewState(fakeApi(new AuthenticationRequiredError()))
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'after'
    state.setDraft(draft)

    await state.save()

    expect(state.state.drafts[1]).toEqual(draft)
    expect(state.dirty.value).toBe(true)
    expect(state.changes.value).toContainEqual({ node_id: 'n-parent', text: 'after\n' })
  })

  it('preserves per-page drafts while navigating', async () => {
    const state = createReviewState(fakeApi())
    await state.load()
    const pageOne = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    pageOne.content![0].content![0].content![0].text = 'page one edit'
    state.setDraft(pageOne)
    state.state.activePage = 2
    const pageTwo = JSON.parse(JSON.stringify(state.state.drafts[2])) as JSONContent
    pageTwo.content![0].content![0].content![0].text = 'page two edit'
    state.setDraft(pageTwo)
    state.state.activePage = 1

    expect(state.state.drafts[1]).toEqual(pageOne)
    expect(state.state.drafts[2]).toEqual(pageTwo)
    expect(state.changes.value.map((change) => change.node_id)).toEqual(['n-parent', 'n-page-2'])
  })

  it('retains drafts and requires explicit reload after a revision conflict', async () => {
    const api = fakeApi(new ReviewApiError('REVIEW_CONFLICT', 409))
    const state = createReviewState(api)
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'conflicting edit'
    state.setDraft(draft)

    await state.save()

    expect(state.state.conflict).toBe(true)
    expect(state.state.drafts[1]).toEqual(draft)
    expect(api.load).toHaveBeenCalledTimes(1)
  })

  it('sends a suggested replacement once and keeps the previewed text', async () => {
    const server = toleranceReviewFixture()
    const api = fakeApi(undefined, server)
    const state = createReviewState(api)
    await state.load()

    state.applyTolerance('finding-tol', 'n-cell-3', 'Tolerance ±0.1%', 'region-hash-tol')
    expect(state.changes.value).toEqual([{ node_id: 'n-cell-3', text: 'Tolerance ±0.1%' }])
    expect(state.state.decisions['finding-tol']?.replacement).toEqual({ node_id: 'n-cell-3', text: 'Tolerance ±0.1%' })

    await state.save()

    expect(api.save).toHaveBeenCalledWith(
      null,
      [],
      [expect.objectContaining({
        finding_id: 'finding-tol',
        action: 'RESOLVED_AFTER_EDIT',
        replacement: { node_id: 'n-cell-3', text: 'Tolerance ±0.1%' },
        expected_region_hash: 'region-hash-tol',
      })],
    )
  })

  it('refuses a stale suggestion and keeps unsaved manual text', async () => {
    const api = fakeApi(undefined, toleranceReviewFixture())
    const state = createReviewState(api)
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    const visit = (node: JSONContent) => {
      if (node.attrs?.sourceId === 'n-cell-3') node.content = [{ type: 'paragraph', content: [{ type: 'text', text: 'manual' }] }]
      else node.content?.forEach(visit)
    }
    visit(draft)
    state.setDraft(draft)

    state.applyTolerance('finding-tol', 'n-cell-3', 'Tolerance ±0.1%', 'region-hash-tol')

    expect(state.state.contentError).toMatch(/no longer matches/)
    expect(state.state.decisions['finding-tol']).toBeUndefined()
    expect(state.changes.value).toEqual([{ node_id: 'n-cell-3', text: 'manual' }])
  })

  it('invalidates a queued replacement when the preview is edited before save', async () => {
    const api = fakeApi(undefined, toleranceReviewFixture())
    const state = createReviewState(api)
    await state.load()
    state.applyTolerance('finding-tol', 'n-cell-3', 'Tolerance ±0.1%', 'region-hash-tol')
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    const visit = (node: JSONContent) => {
      if (node.attrs?.sourceId === 'n-cell-3') node.content = [{ type: 'paragraph', content: [{ type: 'text', text: 'Toler ±0.2%' }] }]
      else node.content?.forEach(visit)
    }
    visit(draft)
    state.setDraft(draft)

    expect(state.state.decisions['finding-tol']).toBeUndefined()
    await state.save()
    expect(api.save).toHaveBeenCalledWith(
      null,
      [{ node_id: 'n-cell-3', text: 'Toler ±0.2%' }],
      [],
    )
  })

  it('replaces a queued finding decision instead of duplicating it in the save payload', async () => {
    const api = fakeApi(undefined, toleranceReviewFixture())
    const state = createReviewState(api)
    await state.load()

    state.decide('finding-tol', 'KEEP_ORIGINAL')
    state.decide('finding-tol', 'ACKNOWLEDGED_LIMITATION')

    expect(Object.values(state.state.decisions)).toEqual([
      { finding_id: 'finding-tol', action: 'ACKNOWLEDGED_LIMITATION', note: null },
    ])

    await state.save()

    expect(api.save).toHaveBeenCalledWith(
      null,
      [],
      [{ finding_id: 'finding-tol', action: 'ACKNOWLEDGED_LIMITATION', note: null }],
    )
    expect(state.state.decisions).toEqual({})
  })
})
