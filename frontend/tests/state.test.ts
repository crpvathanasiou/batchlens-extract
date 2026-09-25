import type { JSONContent } from '@tiptap/core'
import { describe, expect, it, vi } from 'vitest'
import { AuthenticationRequiredError, ReviewApiError, type ReviewApi } from '../src/api'
import {
  memoryPendingStore,
  pendingSaveKey,
  readPendingRecord,
  serializeSaveBody,
  writePendingRecord,
  type PendingSaveRecord,
} from '../src/pendingSave'
import { createReviewState } from '../src/state'
import {
  FIXTURE_HEAD_OTHER,
  FIXTURE_OPERATION_A,
  FIXTURE_OPERATION_B,
  FIXTURE_REVISION_1,
  FIXTURE_REVISION_2,
  inReviewState,
  reviewContextFixture,
  reviewFixture,
  toleranceReviewFixture,
} from './fixture'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function fakeApi(saveError?: Error, server = reviewFixture()): ReviewApi {
  const context = reviewContextFixture(server)
  return {
    load: vi.fn().mockResolvedValue(server),
    context: vi.fn().mockResolvedValue(context),
    lookup: vi.fn().mockResolvedValue({
      context,
      reconciliation: { status: 'UNRESOLVED', head_revision_id: null, head_generation: 0, receipt: null },
    }),
    save: saveError
      ? vi.fn().mockRejectedValue(saveError)
      : vi.fn().mockResolvedValue(inReviewState(server, FIXTURE_REVISION_1, 1)),
    approvePage: vi.fn().mockResolvedValue(server),
    approve: vi.fn().mockResolvedValue({ ...server, status: 'APPROVED', revision_id: FIXTURE_REVISION_2, generation: 2 }),
    exportUrl: vi.fn().mockResolvedValue('/export'),
    fetchSource: vi.fn(),
  }
}

function createTestState(api: ReviewApi) {
  return createReviewState(api, { pendingStore: memoryPendingStore(), scope: 'test-scope' })
}

describe('review state', () => {
  it('keeps an in-memory draft when authentication interrupts saving', async () => {
    const state = createTestState(fakeApi(new AuthenticationRequiredError()))
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
    const state = createTestState(fakeApi())
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
    const state = createTestState(api)
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'conflicting edit'
    state.setDraft(draft)

    await state.save()

    expect(state.state.conflict).toBe(true)
    expect(state.state.drafts[1]).toEqual(draft)
    expect(api.load).toHaveBeenCalledTimes(1)
  })

  it('clears a stale REVIEW_NOT_READY banner after a later document approval succeeds', async () => {
    const server = inReviewState(reviewFixture(), FIXTURE_REVISION_1, 1)
    const approved = { ...server, status: 'APPROVED' as const, revision_id: FIXTURE_REVISION_2, generation: 2 }
    const api = fakeApi(undefined, server)
    vi.mocked(api.approve)
      .mockRejectedValueOnce(new ReviewApiError('REVIEW_NOT_READY', 409))
      .mockResolvedValueOnce(approved)
    const state = createTestState(api)
    await state.load()

    await state.approveDocument()
    expect(state.state.error).toBe('REVIEW_NOT_READY')
    expect(state.state.server?.status).toBe('IN_REVIEW')

    await state.approveDocument()
    expect(state.state.server?.status).toBe('APPROVED')
    expect(state.state.server).toEqual(approved)
    expect(state.state.error).toBeNull()
    expect(state.state.pendingRecord).toBeNull()
    expect(state.blocked.value).toBe(false)
  })

  it('sends a suggested replacement once and keeps the previewed text', async () => {
    const server = toleranceReviewFixture()
    const api = fakeApi(undefined, server)
    const state = createTestState(api)
    await state.load()

    state.applyTolerance('finding-tol', 'n-cell-3', 'Tolerance ±0.1%', 'region-hash-tol')
    expect(state.changes.value).toEqual([{ node_id: 'n-cell-3', text: 'Tolerance ±0.1%' }])
    expect(state.state.decisions['finding-tol']?.replacement).toEqual({ node_id: 'n-cell-3', text: 'Tolerance ±0.1%' })

    await state.save()

    expect(vi.mocked(api.save).mock.calls[0].slice(0, 3)).toEqual([
      null,
      [],
      [expect.objectContaining({
        finding_id: 'finding-tol',
        action: 'RESOLVED_AFTER_EDIT',
        replacement: { node_id: 'n-cell-3', text: 'Tolerance ±0.1%' },
        expected_region_hash: 'region-hash-tol',
      })],
    ])
    expect(vi.mocked(api.save).mock.calls[0][3]).toEqual(expect.objectContaining({
      contextId: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      body: expect.stringContaining('"operation_id"'),
    }))
  })

  it('refuses a stale suggestion and keeps unsaved manual text', async () => {
    const api = fakeApi(undefined, toleranceReviewFixture())
    const state = createTestState(api)
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
    const state = createTestState(api)
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
    expect(vi.mocked(api.save).mock.calls[0].slice(0, 3)).toEqual([
      null,
      [{ node_id: 'n-cell-3', text: 'Toler ±0.2%' }],
      [],
    ])
  })

  it('replaces a queued finding decision instead of duplicating it in the save payload', async () => {
    const api = fakeApi(undefined, toleranceReviewFixture())
    const state = createTestState(api)
    await state.load()

    state.decide('finding-tol', 'KEEP_ORIGINAL')
    state.decide('finding-tol', 'ACKNOWLEDGED_LIMITATION')

    expect(Object.values(state.state.decisions)).toEqual([
      { finding_id: 'finding-tol', action: 'ACKNOWLEDGED_LIMITATION', note: null },
    ])

    await state.save()

    expect(vi.mocked(api.save).mock.calls[0].slice(0, 3)).toEqual([
      null,
      [],
      [{ finding_id: 'finding-tol', action: 'ACKNOWLEDGED_LIMITATION', note: null }],
    ])
    expect(state.state.decisions).toEqual({})
  })

  it('does not send a PUT when pending storage is denied', async () => {
    const api = fakeApi()
    const pendingStore = {
      getItem: () => null,
      setItem: () => {
        throw new Error('quota')
      },
      removeItem: () => undefined,
    }
    const state = createReviewState(api, { pendingStore, scope: 'denied-scope' })
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'after'
    state.setDraft(draft)
    await state.save()
    expect(api.save).not.toHaveBeenCalled()
    expect(state.dirty.value).toBe(true)
    expect(state.state.pendingRecord).toBeNull()
  })

  it('retries the frozen body after reload instead of later editor mutations', async () => {
    const api = fakeApi()
    const pendingStore = memoryPendingStore()
    const first = createReviewState(api, { pendingStore, scope: 'retry-scope' })
    await first.load()
    const draft = JSON.parse(JSON.stringify(first.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'first-save'
    first.setDraft(draft)
    vi.mocked(api.save).mockRejectedValueOnce(new ReviewApiError('INVALID_RESPONSE', 502))
    await first.save()
    const frozen = first.state.pendingRecord?.body
    expect(frozen).toContain('first-save')
    first.abandonWorkspace()
    expect(readPendingRecord(pendingStore, 'retry-scope', reviewContextFixture().context_id)).not.toBeNull()
    const restored = createReviewState(api, { pendingStore, scope: 'retry-scope' })
    await restored.load()
    expect(restored.blocked.value).toBe(true)
    expect(restored.state.saveStatus).toBe('UNKNOWN')
    expect(api.lookup).toHaveBeenCalled()
    await restored.approvePage()
    await restored.approveDocument()
    expect(api.approvePage).not.toHaveBeenCalled()
    expect(api.approve).not.toHaveBeenCalled()
    const mutated = JSON.parse(JSON.stringify(restored.state.drafts[1])) as JSONContent
    mutated.content![0].content![0].content![0].text = 'later-edit'
    restored.state.drafts[1] = mutated
    await restored.retrySameSave()
    const retryBody = vi.mocked(api.save).mock.calls.at(-1)?.[3]?.body
    expect(retryBody).toBe(frozen)
    expect(restored.blocked.value).toBe(false)
  })

  it('keeps a genuine conflict until explicit discard, then allows a new Save ID', async () => {
    const server = reviewFixture()
    const api = fakeApi(new ReviewApiError('REVIEW_CONFLICT', 409), server)
    vi.mocked(api.lookup).mockResolvedValue({
      context: reviewContextFixture(server),
      reconciliation: {
        status: 'UNRESOLVED',
        head_revision_id: FIXTURE_HEAD_OTHER,
        head_generation: 1,
        receipt: null,
      },
    })
    const later = inReviewState(server, FIXTURE_HEAD_OTHER, 1)
    vi.mocked(api.load).mockResolvedValueOnce(server).mockResolvedValue(later)
    const state = createTestState(api)
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'attempted'
    state.setDraft(draft)
    await state.save()
    const originalId = state.state.pendingRecord?.operation_id
    expect(state.state.pendingRecord?.phase).toBe('superseded')
    expect(state.attemptedWork.value?.changes).toEqual([{ node_id: 'n-parent', text: 'attempted\n' }])
    await state.save()
    expect(vi.mocked(api.save).mock.calls).toHaveLength(1)
    await state.acknowledgeAttemptedSave()
    expect(state.blocked.value).toBe(false)
    expect(state.state.server?.revision_id).toBe(FIXTURE_HEAD_OTHER)
    vi.mocked(api.save).mockResolvedValue(inReviewState(later, FIXTURE_REVISION_2, 2))
    const nextDraft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    nextDraft.content![0].content![0].content![0].text = 'new-save'
    state.setDraft(nextDraft)
    await state.save()
    const nextId = vi.mocked(api.save).mock.calls.at(-1)?.[3]?.operationId
    expect(nextId).toBeTruthy()
    expect(nextId).not.toBe(originalId)
  })

  it('does not treat an unresolved lookup with an unchanged head as superseded', async () => {
    const server = inReviewState(reviewFixture(), FIXTURE_REVISION_1, 1)
    const api = fakeApi(new ReviewApiError('REVIEW_CONFLICT', 409), server)
    vi.mocked(api.lookup).mockResolvedValue({
      context: reviewContextFixture(server),
      reconciliation: {
        status: 'UNRESOLVED',
        head_revision_id: FIXTURE_REVISION_1,
        head_generation: 1,
        receipt: null,
      },
    })
    const state = createTestState(api)
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'stuck'
    state.setDraft(draft)
    await state.save()
    expect(state.state.pendingRecord?.phase).toBe('uncertain')
    expect(state.blocked.value).toBe(true)
    await state.acknowledgeAttemptedSave()
    expect(state.state.pendingRecord?.phase).toBe('uncertain')
  })

  it('exposes fingerprint mismatch after a committed lookup replay and keeps the snapshot', async () => {
    const server = reviewFixture()
    const context = reviewContextFixture(server)
    const record: PendingSaveRecord = {
      schema_version: 1,
      context_id: context.context_id,
      job_id: context.job_id,
      actor: context.actor,
      baseline: context.baseline,
      operation_id: FIXTURE_OPERATION_A,
      body: serializeSaveBody(null, [{ node_id: 'n-parent', text: 'divergent\n' }], [], FIXTURE_OPERATION_A),
      expected_revision: null,
      base_generation: 0,
      phase: 'uncertain',
      ambiguous: true,
      message: null,
    }
    const store = memoryPendingStore()
    writePendingRecord(store, 'mismatch-scope', record)
    const api = fakeApi(undefined, server)
    vi.mocked(api.lookup).mockResolvedValue({
      context,
      reconciliation: {
        status: 'COMMITTED',
        head_revision_id: FIXTURE_REVISION_2,
        head_generation: 1,
        receipt: { operation_id: record.operation_id, revision_id: FIXTURE_REVISION_2, generation: 1, replayed: false },
      },
    })
    vi.mocked(api.save).mockRejectedValue(new ReviewApiError('SAVE_OPERATION_MISMATCH', 409))
    const state = createReviewState(api, { pendingStore: store, scope: 'mismatch-scope' })
    await state.load()
    expect(state.state.pendingRecord?.phase).toBe('mismatch')
    expect(state.state.pendingRecord?.body).toContain('divergent')
    expect(state.blocked.value).toBe(true)
  })

  it('ignores a late save response after the workspace is abandoned', async () => {
    const api = fakeApi()
    let finish: (value: ReturnType<typeof reviewFixture>) => void = () => undefined
    vi.mocked(api.save).mockImplementationOnce(
      () => new Promise((resolve) => {
        finish = resolve
      }),
    )
    const first = createTestState(api)
    await first.load()
    const draft = JSON.parse(JSON.stringify(first.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'late'
    first.setDraft(draft)
    const pending = first.save()
    await vi.waitFor(() => expect(first.state.pendingRecord).not.toBeNull())
    const otherServer = { ...reviewFixture(), status: 'APPROVED' as const, revision_id: FIXTURE_REVISION_2, generation: 4 }
    const otherApi = fakeApi(undefined, otherServer)
    const other = createTestState(otherApi)
    await other.load()
    first.abandonWorkspace()
    finish(inReviewState(reviewFixture(), FIXTURE_REVISION_1, 1))
    await pending
    expect(other.state.server?.revision_id).toBe(FIXTURE_REVISION_2)
    expect(other.state.server?.status).toBe('APPROVED')
    expect(other.blocked.value).toBe(false)
  })

  it('isolates another context record and leaves it in storage', async () => {
    const server = reviewFixture()
    const foreign = reviewContextFixture(server, { context_id: 'b'.repeat(64), actor: 'bob' })
    const store = memoryPendingStore()
    writePendingRecord(store, 'shared-scope', {
      schema_version: 1,
      context_id: foreign.context_id,
      job_id: foreign.job_id,
      actor: foreign.actor,
      baseline: foreign.baseline,
      operation_id: FIXTURE_OPERATION_B,
      body: serializeSaveBody(null, [{ node_id: 'n-parent', text: 'bob\n' }], [], FIXTURE_OPERATION_B),
      expected_revision: null,
      base_generation: 0,
      phase: 'uncertain',
      ambiguous: true,
      message: null,
    })
    const state = createReviewState(fakeApi(undefined, server), { pendingStore: store, scope: 'shared-scope' })
    await state.load()
    expect(state.state.pendingRecord).toBeNull()
    expect(state.blocked.value).toBe(false)
    expect(readPendingRecord(store, 'shared-scope', foreign.context_id)).toEqual(
      expect.objectContaining({ actor: 'bob', operation_id: FIXTURE_OPERATION_B }),
    )
  })

  it('blocks recovery for a corrupt record instead of replacing it', async () => {
    const context = reviewContextFixture()
    const store = memoryPendingStore({
      [pendingSaveKey('corrupt-scope', context.context_id)]: '{not-json',
    })
    const api = fakeApi()
    const state = createReviewState(api, { pendingStore: store, scope: 'corrupt-scope' })
    await state.load()
    expect(state.state.corruptPending).toBe(true)
    expect(state.blocked.value).toBe(true)
    await state.save()
    expect(api.save).not.toHaveBeenCalled()
    expect(store.getItem(pendingSaveKey('corrupt-scope', context.context_id))).toBe('{not-json')
  })

  it('keeps a committed record when cleanup fails', async () => {
    const store = memoryPendingStore()
    store.removeItem = () => undefined
    const api = fakeApi()
    const state = createReviewState(api, { pendingStore: store, scope: 'sticky-scope' })
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'committed'
    state.setDraft(draft)
    await state.save()
    expect(state.state.pendingRecord?.phase).toBe('committed')
    expect(state.blocked.value).toBe(true)
    await state.save()
    expect(vi.mocked(api.save).mock.calls).toHaveLength(1)
  })

  it('issues one PUT when two Saves overlap while context is held', async () => {
    const api = fakeApi()
    const state = createTestState(api)
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'once'
    state.setDraft(draft)
    const held = deferred<ReturnType<typeof reviewContextFixture>>()
    const context = reviewContextFixture()
    vi.mocked(api.context).mockImplementation(() => held.promise)
    const first = state.save()
    const second = state.save()
    await vi.waitFor(() => expect(state.state.pending).toBe(true))
    const blockedDraft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    blockedDraft.content![0].content![0].content![0].text = 'mutated-during-prepare'
    state.setDraft(blockedDraft)
    state.decide('finding-tol', 'KEEP_ORIGINAL')
    expect(state.state.decisions).toEqual({})
    expect(api.save).not.toHaveBeenCalled()
    held.resolve(context)
    await Promise.all([first, second])
    expect(api.save).toHaveBeenCalledTimes(1)
    expect(vi.mocked(api.save).mock.calls[0][3]?.body).toContain('once')
    expect(vi.mocked(api.save).mock.calls[0][3]?.body).not.toContain('mutated-during-prepare')
  })

  it('does not start approval or a second Save while a Save is preparing', async () => {
    const api = fakeApi()
    const store = memoryPendingStore()
    const state = createReviewState(api, { pendingStore: store, scope: 'overlap-scope' })
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'prepare'
    state.setDraft(draft)
    const held = deferred<ReturnType<typeof reviewContextFixture>>()
    vi.mocked(api.context).mockImplementation(() => held.promise)
    const saving = state.save()
    await vi.waitFor(() => expect(state.state.pending).toBe(true))
    await state.approvePage()
    await state.save()
    expect(api.save).not.toHaveBeenCalled()
    expect(api.approvePage).not.toHaveBeenCalled()
    held.resolve(reviewContextFixture())
    await saving
    expect(api.save).toHaveBeenCalledTimes(1)
    expect(api.approvePage).not.toHaveBeenCalled()
  })

  it('does not let Check and Retry overlap, and an older finally cannot unlock a newer action', async () => {
    const api = fakeApi()
    const store = memoryPendingStore()
    const state = createReviewState(api, { pendingStore: store, scope: 'check-retry-scope' })
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'held'
    state.setDraft(draft)
    vi.mocked(api.save).mockRejectedValueOnce(new ReviewApiError('INVALID_RESPONSE', 502))
    await state.save()
    const firstId = state.state.pendingRecord?.operation_id
    const held = deferred<ReturnType<typeof reviewContextFixture>>()
    vi.mocked(api.context).mockImplementation(() => held.promise)
    const checking = state.checkSaveStatus()
    const retrying = state.retrySameSave()
    await vi.waitFor(() => expect(state.state.pending).toBe(true))
    held.resolve(reviewContextFixture())
    await Promise.all([checking, retrying])
    expect(api.lookup).toHaveBeenCalled()
    expect(vi.mocked(api.save).mock.calls).toHaveLength(1)
    expect(state.state.pendingRecord?.operation_id).toBe(firstId)

    const saveHeld = deferred<ReturnType<typeof inReviewState>>()
    const checkHeld = deferred<ReturnType<typeof reviewContextFixture>>()
    vi.mocked(api.context).mockResolvedValue(reviewContextFixture())
    vi.mocked(api.save).mockImplementationOnce(() => saveHeld.promise)
    const retry = state.retrySameSave()
    await vi.waitFor(() => expect(api.save).toHaveBeenCalledTimes(2))
    state.abandonWorkspace()
    vi.mocked(api.context).mockImplementation(() => checkHeld.promise)
    const checkingLater = state.checkSaveStatus()
    await vi.waitFor(() => expect(state.state.pending).toBe(true))
    saveHeld.resolve(inReviewState())
    await retry
    expect(state.state.pending).toBe(true)
    expect(state.state.pendingRecord?.operation_id).toBe(firstId)
    vi.mocked(api.context).mockResolvedValue(reviewContextFixture())
    checkHeld.resolve(reviewContextFixture())
    await checkingLater
    expect(state.state.pendingRecord?.operation_id).toBe(firstId)
    expect(state.blocked.value).toBe(true)
  })

  it('does not apply a late success or failure from A onto later work B', async () => {
    const api = fakeApi()
    const store = memoryPendingStore()
    const state = createReviewState(api, { pendingStore: store, scope: 'late-ab-scope' })
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'operation-a'
    state.setDraft(draft)
    const held = deferred<ReturnType<typeof inReviewState>>()
    vi.mocked(api.save).mockImplementationOnce(() => held.promise)
    const first = state.save()
    await vi.waitFor(() => expect(state.state.pendingRecord).not.toBeNull())
    const firstId = state.state.pendingRecord?.operation_id
    const firstBody = state.state.pendingRecord?.body
    state.abandonWorkspace()
    const restored = createReviewState(api, { pendingStore: store, scope: 'late-ab-scope' })
    vi.mocked(api.save).mockRejectedValueOnce(new ReviewApiError('HTTP_500', 500))
    await restored.load()
    expect(restored.state.pendingRecord?.operation_id).toBe(firstId)
    await restored.retrySameSave()
    expect(restored.state.pendingRecord?.phase).toBe('uncertain')
    held.resolve(inReviewState())
    await first
    expect(restored.state.pendingRecord?.operation_id).toBe(firstId)
    expect(restored.state.pendingRecord?.body).toBe(firstBody)
    expect(restored.state.server?.revision_id).toBeNull()
  })

  it('retains the original record when context changes during PUT', async () => {
    const api = fakeApi()
    const store = memoryPendingStore()
    const state = createReviewState(api, { pendingStore: store, scope: 'ctx-change-scope' })
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'context-a'
    state.setDraft(draft)
    const held = deferred<ReturnType<typeof inReviewState>>()
    vi.mocked(api.save).mockImplementationOnce(() => held.promise)
    const saving = state.save()
    await vi.waitFor(() => expect(state.state.pendingRecord).not.toBeNull())
    const original = state.state.pendingRecord
    const switched = reviewContextFixture(reviewFixture(), { context_id: 'b'.repeat(64), actor: 'bob' })
    vi.mocked(api.context).mockResolvedValue(switched)
    held.resolve(inReviewState())
    await saving
    expect(state.state.pendingRecord?.operation_id).toBe(original?.operation_id)
    expect(state.state.pendingRecord?.body).toBe(original?.body)
    expect(state.state.server?.revision_id).toBeNull()
    expect(readPendingRecord(store, 'ctx-change-scope', reviewContextFixture().context_id)).toEqual(
      expect.objectContaining({ operation_id: original?.operation_id, body: original?.body }),
    )
  })

  it('still recovers after a same-actor token refresh', async () => {
    const api = fakeApi()
    const store = memoryPendingStore()
    const state = createReviewState(api, { pendingStore: store, scope: 'token-scope' })
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'refresh'
    state.setDraft(draft)
    vi.mocked(api.save).mockRejectedValueOnce(new ReviewApiError('INVALID_RESPONSE', 502))
    await state.save()
    vi.mocked(api.context).mockResolvedValue(reviewContextFixture())
    vi.mocked(api.lookup).mockResolvedValue({
      context: reviewContextFixture(),
      reconciliation: {
        status: 'COMMITTED',
        head_revision_id: FIXTURE_REVISION_1,
        head_generation: 1,
        receipt: { operation_id: state.state.pendingRecord!.operation_id, revision_id: FIXTURE_REVISION_1, generation: 1, replayed: false },
      },
    })
    vi.mocked(api.save).mockResolvedValue(inReviewState())
    await state.checkSaveStatus()
    expect(state.blocked.value).toBe(false)
    expect(state.state.server?.revision_id).toBe(FIXTURE_REVISION_1)
  })

  it('keeps B and its approvals when an exact retry of A returns newer B', async () => {
    const approvedB = {
      ...inReviewState(reviewFixture(), FIXTURE_REVISION_2, 2),
      status: 'APPROVED' as const,
      pages: reviewFixture().pages.map((page) => ({
        ...page,
        approval: {
          content_hash: page.content_hash,
          actor: 'alice',
          at: '2026-01-01T00:00:00Z',
          revision_id: FIXTURE_REVISION_2,
        },
      })),
    }
    const api = fakeApi()
    const store = memoryPendingStore()
    const state = createReviewState(api, { pendingStore: store, scope: 'gen-scope' })
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'a-then-b'
    state.setDraft(draft)
    vi.mocked(api.save).mockRejectedValueOnce(new ReviewApiError('INVALID_RESPONSE', 502))
    await state.save()
    state.state.server = approvedB
    vi.mocked(api.save).mockResolvedValue(approvedB)
    await state.retrySameSave()
    expect(state.state.server?.revision_id).toBe(FIXTURE_REVISION_2)
    expect(state.state.server?.generation).toBe(2)
    expect(state.state.server?.status).toBe('APPROVED')
    expect(state.state.server?.pages.every((page) => page.approval)).toBe(true)
    expect(state.blocked.value).toBe(false)
  })

  it('rejects a same-context generation regression and keeps the newer state', async () => {
    const api = fakeApi()
    const state = createTestState(api)
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'older-replay'
    state.setDraft(draft)
    vi.mocked(api.save).mockRejectedValueOnce(new ReviewApiError('INVALID_RESPONSE', 502))
    await state.save()
    state.state.server = inReviewState(reviewFixture(), FIXTURE_REVISION_2, 2)
    vi.mocked(api.save).mockResolvedValue(inReviewState(reviewFixture(), FIXTURE_REVISION_1, 1))
    await state.retrySameSave()
    expect(state.state.server?.revision_id).toBe(FIXTURE_REVISION_2)
    expect(state.state.server?.generation).toBe(2)
    expect(state.state.pendingRecord).not.toBeNull()
    expect(state.blocked.value).toBe(true)
  })

  it('treats a current-key actor mismatch as corrupt recovery data', async () => {
    const server = reviewFixture()
    const context = reviewContextFixture(server)
    const store = memoryPendingStore()
    writePendingRecord(store, 'actor-scope', {
      schema_version: 1,
      context_id: context.context_id,
      job_id: context.job_id,
      actor: 'mallory',
      baseline: context.baseline,
      operation_id: FIXTURE_OPERATION_A,
      body: serializeSaveBody(null, [{ node_id: 'n-parent', text: 'stolen\n' }], [], FIXTURE_OPERATION_A),
      expected_revision: null,
      base_generation: 0,
      phase: 'uncertain',
      ambiguous: true,
      message: null,
    })
    const api = fakeApi(undefined, server)
    const state = createReviewState(api, { pendingStore: store, scope: 'actor-scope' })
    await state.load()
    expect(state.state.corruptPending).toBe(true)
    expect(state.blocked.value).toBe(true)
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'replacement'
    state.setDraft(draft)
    await state.save()
    expect(api.save).not.toHaveBeenCalled()
    const retained = store.getItem(pendingSaveKey('actor-scope', context.context_id))
    expect(retained).toContain('mallory')
    expect(retained).toContain('stolen')
  })

  it('does not treat an unknown lookup status as superseded', async () => {
    const api = fakeApi(new ReviewApiError('REVIEW_CONFLICT', 409))
    vi.mocked(api.lookup).mockResolvedValue({
      context: reviewContextFixture(),
      reconciliation: {
        status: 'INVALID_STATUS' as 'UNRESOLVED',
        head_revision_id: FIXTURE_HEAD_OTHER,
        head_generation: 1,
        receipt: null,
      },
    })
    const state = createTestState(api)
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'unknown-status'
    state.setDraft(draft)
    await state.save()
    expect(state.state.pendingRecord?.phase).toBe('uncertain')
    expect(state.state.error).toMatch(/Save status unknown/)
    await state.acknowledgeAttemptedSave()
    expect(state.state.pendingRecord?.phase).toBe('uncertain')
  })

  it('does not retire work when PUT returns an initial NOT_REVIEWED shell', async () => {
    const api = fakeApi()
    const state = createTestState(api)
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'shell'
    state.setDraft(draft)
    vi.mocked(api.save).mockResolvedValue(reviewFixture())
    await state.save()
    expect(state.state.pendingRecord).not.toBeNull()
    expect(state.state.drafts[1]).toEqual(draft)
    expect(state.state.error).toMatch(/Save status unknown/)
  })

  it('describes a successful commit as committed when remove and metadata writes fail', async () => {
    const store = memoryPendingStore()
    const api = fakeApi()
    const state = createReviewState(api, { pendingStore: store, scope: 'commit-fail-scope' })
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'kept-commit'
    state.setDraft(draft)
    const originalSet = store.setItem.bind(store)
    let writes = 0
    store.setItem = (key, value) => {
      writes += 1
      if (writes === 1) {
        originalSet(key, value)
        return
      }
      throw new Error('quota')
    }
    store.removeItem = () => undefined
    await state.save()
    expect(state.state.knownCommit).toBe(true)
    expect(state.state.pendingRecord?.phase).toBe('committed')
    expect(state.state.error).toMatch(/committed/)
    expect(state.state.error).not.toMatch(/was not sent/)
    expect(state.state.server?.revision_id).toBe(FIXTURE_REVISION_1)
    expect(state.state.drafts[1]).not.toEqual(draft)
    await state.save()
    expect(api.save).toHaveBeenCalledTimes(1)
  })

  it('does not mark a previously ambiguous attempt as rejected from a later 422', async () => {
    const api = fakeApi()
    const state = createTestState(api)
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'ambiguous'
    state.setDraft(draft)
    vi.mocked(api.save).mockRejectedValueOnce(new ReviewApiError('INVALID_RESPONSE', 502))
    await state.save()
    expect(state.state.pendingRecord?.ambiguous).toBe(true)
    vi.mocked(api.save).mockRejectedValueOnce(new ReviewApiError('INVALID_REVIEW', 422))
    await state.retrySameSave()
    expect(state.state.pendingRecord?.phase).toBe('uncertain')
    expect(state.state.pendingRecord?.ambiguous).toBe(true)
  })

  it('presents manual text, all three finding actions, and suggestion details after recovery', async () => {
    const server = toleranceReviewFixture()
    const context = reviewContextFixture(server)
    const body = serializeSaveBody(
      null,
      [{ node_id: 'n-parent', text: 'manual-attempt\n' }],
      [
        { finding_id: 'finding-tol', action: 'RESOLVED_AFTER_EDIT', replacement: { node_id: 'n-cell-3', text: 'Tolerance ±0.1%' }, expected_region_hash: 'region-hash-tol', note: 'check source' },
        { finding_id: 'finding-keep', action: 'KEEP_ORIGINAL', note: null },
        { finding_id: 'finding-limit', action: 'ACKNOWLEDGED_LIMITATION', note: 'known limitation' },
      ],
      FIXTURE_OPERATION_A,
    )
    const store = memoryPendingStore()
    writePendingRecord(store, 'attempted-scope', {
      schema_version: 1,
      context_id: context.context_id,
      job_id: context.job_id,
      actor: context.actor,
      baseline: context.baseline,
      operation_id: FIXTURE_OPERATION_A,
      body,
      expected_revision: null,
      base_generation: 0,
      phase: 'uncertain',
      ambiguous: true,
      message: null,
    })
    const api = fakeApi(undefined, server)
    const state = createReviewState(api, { pendingStore: store, scope: 'attempted-scope' })
    await state.load()
    expect(state.attemptedWork.value?.textItems.some((item) => item.text.includes('manual-attempt'))).toBe(true)
    expect(state.attemptedWork.value?.decisionItems.map((item) => item.actionLabel)).toEqual([
      'Mark resolved after edit',
      'Keep original',
      'Acknowledge limitation',
    ])
    expect(state.attemptedWork.value?.decisionItems[0]?.replacement).toBe('Tolerance ±0.1%')
    expect(state.attemptedWork.value?.decisionItems[0]?.note).toBe('check source')
    expect(state.attemptedWork.value?.decisionItems[0]?.pageLabel).toBe('Page 1')
    await state.acknowledgeAttemptedSave()
    expect(state.blocked.value).toBe(true)
    expect(state.state.pendingRecord?.phase).toBe('uncertain')
  })

  it('does not automatically approve after a successful recovery', async () => {
    const api = fakeApi()
    const store = memoryPendingStore()
    const state = createReviewState(api, { pendingStore: store, scope: 'no-auto-approve' })
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'recover-only'
    state.setDraft(draft)
    vi.mocked(api.save).mockRejectedValueOnce(new ReviewApiError('INVALID_RESPONSE', 502))
    await state.save()
    vi.mocked(api.save).mockResolvedValue(inReviewState())
    await state.retrySameSave()
    expect(state.blocked.value).toBe(false)
    expect(api.approvePage).not.toHaveBeenCalled()
    expect(api.approve).not.toHaveBeenCalled()
  })

  it('does not send a new operation when storage already has a current-key record', async () => {
    const api = fakeApi()
    const store = memoryPendingStore()
    const state = createReviewState(api, { pendingStore: store, scope: 'existing-scope' })
    await state.load()
    writePendingRecord(store, 'existing-scope', {
      schema_version: 1,
      context_id: reviewContextFixture().context_id,
      job_id: 'job',
      actor: 'alice',
      baseline: reviewFixture().catalogue.baseline,
      operation_id: FIXTURE_OPERATION_A,
      body: serializeSaveBody(null, [{ node_id: 'n-parent', text: 'already-pending\n' }], [], FIXTURE_OPERATION_A),
      expected_revision: null,
      base_generation: 0,
      phase: 'uncertain',
      ambiguous: true,
      message: null,
    })
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'second-attempt'
    state.setDraft(draft)
    await state.save()
    expect(api.save).not.toHaveBeenCalled()
    expect(state.state.pendingRecord?.operation_id).toBe(FIXTURE_OPERATION_A)
    expect(state.state.pendingRecord?.body).toContain('already-pending')
    expect(store.getItem(pendingSaveKey('existing-scope', reviewContextFixture().context_id))).toContain('already-pending')
  })

  it('does not pair a loaded ReviewState with a later context', async () => {
    const api = fakeApi()
    const held = deferred<ReturnType<typeof reviewFixture>>()
    vi.mocked(api.load).mockImplementationOnce(() => held.promise)
    const state = createTestState(api)
    const loading = state.load()
    await vi.waitFor(() => expect(api.load).toHaveBeenCalled())
    vi.mocked(api.context).mockResolvedValue(reviewContextFixture(reviewFixture(), { context_id: 'b'.repeat(64), actor: 'bob' }))
    held.resolve(reviewFixture())
    await loading
    expect(state.state.server).toBeNull()
    expect(state.state.error).toBeTruthy()
  })

  it('does not treat a mismatched lookup receipt as confirmation', async () => {
    const api = fakeApi(new ReviewApiError('REVIEW_CONFLICT', 409))
    vi.mocked(api.lookup).mockResolvedValue({
      context: reviewContextFixture(),
      reconciliation: {
        status: 'COMMITTED',
        head_revision_id: FIXTURE_REVISION_1,
        head_generation: 1,
        receipt: { operation_id: FIXTURE_OPERATION_B, revision_id: FIXTURE_REVISION_1, generation: 1, replayed: false },
      },
    })
    const state = createTestState(api)
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'wrong-receipt'
    state.setDraft(draft)
    await state.save()
    expect(state.state.pendingRecord?.phase).toBe('uncertain')
    expect(state.state.error).toMatch(/Save status unknown/)
  })

  it('keeps a committed Save when the returned document cannot be projected', async () => {
    const api = fakeApi()
    const state = createTestState(api)
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'unprojectable'
    state.setDraft(draft)
    const empty = inReviewState()
    empty.document = { ...empty.document, pages: [] }
    vi.mocked(api.save).mockResolvedValue(empty)
    await state.save()
    expect(state.state.knownCommit).toBe(true)
    expect(state.state.pendingRecord).not.toBeNull()
    expect(state.state.drafts[1]).toEqual(draft)
    expect(state.state.error).toMatch(/committed/)
    expect(state.state.error).not.toMatch(/was not sent/)
  })

  it('does not claim a persisted commit after reload when only the uncertain record survived', async () => {
    const store = memoryPendingStore()
    const api = fakeApi()
    const state = createReviewState(api, { pendingStore: store, scope: 'reload-uncertain-scope' })
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'survived-uncertain'
    state.setDraft(draft)
    const originalSet = store.setItem.bind(store)
    const originalRemove = store.removeItem.bind(store)
    let writes = 0
    store.setItem = (key, value) => {
      writes += 1
      if (writes === 1) {
        originalSet(key, value)
        return
      }
      throw new Error('quota')
    }
    store.removeItem = () => undefined
    await state.save()
    expect(state.state.knownCommit).toBe(true)
    store.setItem = originalSet
    store.removeItem = originalRemove
    const restored = createReviewState(api, { pendingStore: store, scope: 'reload-uncertain-scope' })
    await restored.load()
    expect(restored.state.knownCommit).toBe(false)
    expect(restored.state.pendingRecord?.phase).toBe('uncertain')
    expect(restored.state.pendingRecord?.body).toContain('survived-uncertain')
    expect(restored.state.error).not.toMatch(/committed, but/)
  })

  it('does not apply or clear a superseded record when context changes during discard load', async () => {
    const server = reviewFixture()
    const store = memoryPendingStore()
    const api = fakeApi(new ReviewApiError('REVIEW_CONFLICT', 409), server)
    vi.mocked(api.lookup).mockResolvedValue({
      context: reviewContextFixture(server),
      reconciliation: {
        status: 'UNRESOLVED',
        head_revision_id: FIXTURE_HEAD_OTHER,
        head_generation: 1,
        receipt: null,
      },
    })
    const later = inReviewState(server, FIXTURE_HEAD_OTHER, 1)
    vi.mocked(api.load).mockResolvedValueOnce(server).mockResolvedValue(later)
    const state = createReviewState(api, { pendingStore: store, scope: 'discard-ctx-scope' })
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'keep-me'
    state.setDraft(draft)
    await state.save()
    const originalId = state.state.pendingRecord?.operation_id
    const originalBody = state.state.pendingRecord?.body
    expect(state.state.pendingRecord?.phase).toBe('superseded')
    const held = deferred<ReturnType<typeof inReviewState>>()
    vi.mocked(api.load).mockImplementation(() => held.promise)
    const disposing = state.acknowledgeAttemptedSave()
    await vi.waitFor(() => expect(api.load).toHaveBeenCalledTimes(2))
    vi.mocked(api.context).mockResolvedValue(reviewContextFixture(server, { context_id: 'b'.repeat(64), actor: 'bob' }))
    held.resolve(inReviewState(server, FIXTURE_REVISION_2, 2))
    await disposing
    expect(state.state.pendingRecord?.operation_id).toBe(originalId)
    expect(state.state.pendingRecord?.body).toBe(originalBody)
    expect(state.state.pendingRecord?.phase).toBe('superseded')
    expect(state.state.server?.revision_id).toBeNull()
    expect(state.state.drafts[1]).toEqual(draft)
    expect(state.blocked.value).toBe(true)
    expect(readPendingRecord(store, 'discard-ctx-scope', reviewContextFixture().context_id)).toEqual(
      expect.objectContaining({ operation_id: originalId, body: originalBody }),
    )
  })

  it('still discards a superseded Save when context is unchanged', async () => {
    const server = reviewFixture()
    const api = fakeApi(new ReviewApiError('REVIEW_CONFLICT', 409), server)
    vi.mocked(api.lookup).mockResolvedValue({
      context: reviewContextFixture(server),
      reconciliation: {
        status: 'UNRESOLVED',
        head_revision_id: FIXTURE_HEAD_OTHER,
        head_generation: 1,
        receipt: null,
      },
    })
    const later = inReviewState(server, FIXTURE_HEAD_OTHER, 1)
    vi.mocked(api.load).mockResolvedValueOnce(server).mockResolvedValue(later)
    const state = createTestState(api)
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'discard-ok'
    state.setDraft(draft)
    await state.save()
    expect(state.state.pendingRecord?.phase).toBe('superseded')
    await state.acknowledgeAttemptedSave()
    expect(state.blocked.value).toBe(false)
    expect(state.state.pendingRecord).toBeNull()
    expect(state.state.server?.revision_id).toBe(FIXTURE_HEAD_OTHER)
  })

  it('does not apply mismatch state when context changes during the follow-up GET', async () => {
    const server = reviewFixture()
    const store = memoryPendingStore()
    const api = fakeApi(undefined, server)
    const state = createReviewState(api, { pendingStore: store, scope: 'mismatch-ctx-scope' })
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'mismatch-keep'
    state.setDraft(draft)
    vi.mocked(api.lookup).mockImplementation(async (operationId) => ({
      context: reviewContextFixture(server),
      reconciliation: {
        status: 'COMMITTED' as const,
        head_revision_id: FIXTURE_REVISION_1,
        head_generation: 1,
        receipt: { operation_id: operationId, revision_id: FIXTURE_REVISION_1, generation: 1, replayed: false },
      },
    }))
    const held = deferred<ReturnType<typeof inReviewState>>()
    vi.mocked(api.load).mockImplementation(() => held.promise)
    vi.mocked(api.save).mockRejectedValueOnce(new ReviewApiError('SAVE_OPERATION_MISMATCH', 409))
    const saving = state.save()
    await vi.waitFor(() => expect(api.load).toHaveBeenCalledTimes(2))
    const originalId = state.state.pendingRecord?.operation_id
    const originalBody = state.state.pendingRecord?.body
    vi.mocked(api.context).mockResolvedValue(reviewContextFixture(server, { context_id: 'b'.repeat(64), actor: 'bob' }))
    held.resolve(inReviewState(server, FIXTURE_REVISION_2, 2))
    await saving
    expect(state.state.pendingRecord?.operation_id).toBe(originalId)
    expect(state.state.pendingRecord?.body).toBe(originalBody)
    expect(state.state.pendingRecord?.phase).not.toBe('mismatch')
    expect(state.state.server?.revision_id).toBeNull()
    expect(state.state.drafts[1]).toEqual(draft)
    expect(state.blocked.value).toBe(true)
    expect(readPendingRecord(store, 'mismatch-ctx-scope', reviewContextFixture().context_id)).toEqual(
      expect.objectContaining({ operation_id: originalId, body: originalBody }),
    )
  })

  it('does not mark superseded when context changes after conflict lookup', async () => {
    const server = reviewFixture()
    const store = memoryPendingStore()
    const api = fakeApi(new ReviewApiError('REVIEW_CONFLICT', 409), server)
    const state = createReviewState(api, { pendingStore: store, scope: 'conflict-ctx-scope' })
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'conflict-keep'
    state.setDraft(draft)
    const held = deferred<Awaited<ReturnType<ReviewApi['lookup']>>>()
    vi.mocked(api.lookup).mockImplementation(() => held.promise)
    const saving = state.save()
    await vi.waitFor(() => expect(api.lookup).toHaveBeenCalled())
    const originalId = state.state.pendingRecord?.operation_id
    const originalBody = state.state.pendingRecord?.body
    vi.mocked(api.context).mockResolvedValue(reviewContextFixture(server, { context_id: 'b'.repeat(64), actor: 'bob' }))
    held.resolve({
      context: reviewContextFixture(server),
      reconciliation: {
        status: 'UNRESOLVED',
        head_revision_id: FIXTURE_HEAD_OTHER,
        head_generation: 1,
        receipt: null,
      },
    })
    await saving
    expect(state.state.pendingRecord?.operation_id).toBe(originalId)
    expect(state.state.pendingRecord?.body).toBe(originalBody)
    expect(state.state.pendingRecord?.phase).not.toBe('superseded')
    expect(state.blocked.value).toBe(true)
    await state.acknowledgeAttemptedSave()
    expect(state.state.pendingRecord?.operation_id).toBe(originalId)
  })

  it('does not treat a later 422 as rejection after a lost response and failed metadata write', async () => {
    const store = memoryPendingStore()
    const api = fakeApi()
    const state = createReviewState(api, { pendingStore: store, scope: 'later-422-scope' })
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'lost-then-422'
    state.setDraft(draft)
    const originalSet = store.setItem.bind(store)
    let writes = 0
    store.setItem = (key, value) => {
      writes += 1
      if (writes === 1) {
        originalSet(key, value)
        return
      }
      throw new Error('quota')
    }
    vi.mocked(api.save).mockRejectedValueOnce(new ReviewApiError('INVALID_RESPONSE', 502))
    await state.save()
    expect(api.save).toHaveBeenCalledTimes(1)
    expect(state.state.pendingRecord?.ambiguous).toBe(true)
    expect(state.state.error).not.toMatch(/was not sent/)
    expect(state.blocked.value).toBe(true)
    const stored = readPendingRecord(store, 'later-422-scope', reviewContextFixture().context_id)
    expect(stored === 'corrupt' ? null : stored?.ambiguous).toBe(false)
    store.setItem = originalSet
    vi.mocked(api.save).mockRejectedValueOnce(new ReviewApiError('INVALID_REVIEW', 422))
    await state.retrySameSave()
    expect(state.state.pendingRecord?.phase).toBe('uncertain')
    expect(state.state.pendingRecord?.ambiguous).toBe(true)
    await state.acknowledgeAttemptedSave()
    expect(state.state.pendingRecord?.phase).toBe('uncertain')
    expect(state.blocked.value).toBe(true)
  })

  it('does not infer a safe rejection from a recovered older record and a later 422', async () => {
    const store = memoryPendingStore()
    const api = fakeApi()
    const first = createReviewState(api, { pendingStore: store, scope: 'reload-422-scope' })
    await first.load()
    const draft = JSON.parse(JSON.stringify(first.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'recovered-422'
    first.setDraft(draft)
    vi.mocked(api.save).mockRejectedValueOnce(new ReviewApiError('INVALID_RESPONSE', 502))
    await first.save()
    first.abandonWorkspace()
    const restored = createReviewState(api, { pendingStore: store, scope: 'reload-422-scope' })
    await restored.load()
    expect(restored.state.pendingRecord?.ambiguous).toBe(true)
    vi.mocked(api.save).mockRejectedValueOnce(new ReviewApiError('INVALID_REVIEW', 422))
    await restored.retrySameSave()
    expect(restored.state.pendingRecord?.phase).toBe('uncertain')
    await restored.acknowledgeAttemptedSave()
    expect(restored.state.pendingRecord?.phase).toBe('uncertain')
    expect(restored.blocked.value).toBe(true)
  })

  it('still allows explicit discard after a first unambiguous validation rejection', async () => {
    const api = fakeApi()
    const state = createTestState(api)
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'first-422'
    state.setDraft(draft)
    vi.mocked(api.save).mockRejectedValueOnce(new ReviewApiError('INVALID_REVIEW', 422))
    await state.save()
    expect(state.state.pendingRecord?.phase).toBe('rejected')
    expect(state.state.pendingRecord?.ambiguous).toBe(false)
    await state.acknowledgeAttemptedSave()
    expect(state.blocked.value).toBe(false)
    expect(state.state.pendingRecord).toBeNull()
  })

  it('does not treat an unresolved lookup with a non-null head and generation 0 as superseded', async () => {
    const api = fakeApi(new ReviewApiError('REVIEW_CONFLICT', 409))
    vi.mocked(api.lookup).mockResolvedValue({
      context: reviewContextFixture(),
      reconciliation: {
        status: 'UNRESOLVED',
        head_revision_id: FIXTURE_HEAD_OTHER,
        head_generation: 0,
        receipt: null,
      },
    })
    const state = createTestState(api)
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'bad-head'
    state.setDraft(draft)
    await state.save()
    expect(state.state.pendingRecord?.phase).toBe('uncertain')
    await state.acknowledgeAttemptedSave()
    expect(state.state.pendingRecord?.phase).toBe('uncertain')
  })

  it('does not confirm a lookup whose context identity does not match the pending Save', async () => {
    const api = fakeApi(new ReviewApiError('REVIEW_CONFLICT', 409))
    vi.mocked(api.lookup).mockResolvedValue({
      context: reviewContextFixture(reviewFixture(), { actor: 'mallory' }),
      reconciliation: {
        status: 'UNRESOLVED',
        head_revision_id: FIXTURE_HEAD_OTHER,
        head_generation: 1,
        receipt: null,
      },
    })
    const state = createTestState(api)
    await state.load()
    const draft = JSON.parse(JSON.stringify(state.state.drafts[1])) as JSONContent
    draft.content![0].content![0].content![0].text = 'wrong-actor'
    state.setDraft(draft)
    await state.save()
    expect(state.state.pendingRecord?.phase).toBe('uncertain')
    await state.acknowledgeAttemptedSave()
    expect(state.state.pendingRecord?.phase).toBe('uncertain')
  })
})
