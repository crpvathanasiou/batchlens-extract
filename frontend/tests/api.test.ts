import { afterEach, describe, expect, it, vi } from 'vitest'
import { createReviewApi, isOperationLookup, ReviewApiError } from '../src/api'
import { FIXTURE_OPERATION_A, FIXTURE_REVISION_1, FIXTURE_REVISION_2, reviewContextFixture, reviewFixture } from './fixture'

afterEach(() => vi.unstubAllGlobals())

describe('review API contract', () => {
  it('uses the job review endpoint, no-store, and corrected update body', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(reviewFixture()), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetch)
    const api = createReviewApi('job/1', () => 'token', vi.fn())
    await api.save(null, [{ node_id: 'node-1', text: 'updated' }], [])

    expect(fetch).toHaveBeenCalledWith('/api/v1/documents/jobs/job%2F1/review', expect.objectContaining({
      method: 'PUT',
      cache: 'no-store',
      body: JSON.stringify({
        expected_revision: null,
        changes: [{ node_id: 'node-1', text: 'updated' }],
        decisions: [],
      }),
      headers: expect.objectContaining({ Authorization: 'Bearer token', 'Cache-Control': 'no-store' }),
    }))
  })

  it('exposes only a safe error code and invokes authentication recovery', async () => {
    const authentication = vi.fn()
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response('<provider detail>', { status: 500 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ code: 'UNAUTHORIZED' }), { status: 401 }))
    vi.stubGlobal('fetch', fetch)
    const api = createReviewApi('job', () => null, authentication)

    await expect(api.load()).rejects.toEqual(new ReviewApiError('HTTP_500', 500))
    await expect(api.load()).rejects.toThrow('Authentication is required.')
    expect(authentication).toHaveBeenCalledOnce()
  })

  it('sends the frozen body and review context header for an operation-aware save', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(reviewFixture()), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetch)
    const api = createReviewApi('job', () => 'token', vi.fn())
    const body = '{"expected_revision":null,"changes":[],"decisions":[],"operation_id":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}'
    await api.save(null, [], [], {
      operationId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      contextId: 'a'.repeat(64),
      body,
    })
    expect(fetch).toHaveBeenCalledWith('/api/v1/documents/jobs/job/review', expect.objectContaining({
      method: 'PUT',
      body,
      headers: expect.objectContaining({
        Authorization: 'Bearer token',
        'X-Review-Context': 'a'.repeat(64),
      }),
    }))
  })

  it('requires the context header for operation lookup', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      context: {
        schema_version: 1,
        context_id: 'a'.repeat(64),
        job_id: 'job',
        actor: 'alice',
        baseline: { key: 'document.json', version: '1', content_type: 'application/json' },
      },
      reconciliation: { status: 'UNRESOLVED', head_revision_id: null, head_generation: 0, receipt: null },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetch)
    const api = createReviewApi('job', () => 'token', vi.fn())
    await api.lookup('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'a'.repeat(64))
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/documents/jobs/job/review/operations/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      expect.objectContaining({
        headers: expect.objectContaining({ 'X-Review-Context': 'a'.repeat(64) }),
      }),
    )
  })

  it('rejects invalid context and lookup success payloads', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ schema_version: 1, context_id: 'nope' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        context: {
          schema_version: 1,
          context_id: 'a'.repeat(64),
          job_id: 'job',
          actor: 'alice',
          baseline: { key: 'document.json', version: '1', content_type: 'application/json' },
        },
        reconciliation: { status: 'INVALID_STATUS', head_revision_id: null, head_generation: 0, receipt: null },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetch)
    const api = createReviewApi('job', () => 'token', vi.fn())
    await expect(api.context()).rejects.toEqual(new ReviewApiError('INVALID_RESPONSE', 502))
    await expect(api.lookup('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'a'.repeat(64))).rejects.toEqual(
      new ReviewApiError('INVALID_RESPONSE', 502),
    )
  })

  it('rejects an invalid ReviewState success payload', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'IN_REVIEW', revision_id: null, generation: 0 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetch)
    const api = createReviewApi('job', () => 'token', vi.fn())
    await expect(api.load()).rejects.toEqual(new ReviewApiError('INVALID_RESPONSE', 502))
  })

  it('rejects incoherent lookup heads and receipt ordering', async () => {
    const context = reviewContextFixture()
    expect(isOperationLookup({
      context,
      reconciliation: { status: 'UNRESOLVED', head_revision_id: FIXTURE_REVISION_1, head_generation: 0, receipt: null },
    })).toBe(false)
    expect(isOperationLookup({
      context,
      reconciliation: { status: 'UNRESOLVED', head_revision_id: null, head_generation: 1, receipt: null },
    })).toBe(false)
    expect(isOperationLookup({
      context,
      reconciliation: {
        status: 'COMMITTED',
        head_revision_id: FIXTURE_REVISION_1,
        head_generation: 1,
        receipt: { operation_id: FIXTURE_OPERATION_A, revision_id: FIXTURE_REVISION_2, generation: 2, replayed: false },
      },
    })).toBe(false)
    expect(isOperationLookup({
      context,
      reconciliation: {
        status: 'COMMITTED',
        head_revision_id: FIXTURE_REVISION_2,
        head_generation: 2,
        receipt: { operation_id: FIXTURE_OPERATION_A, revision_id: FIXTURE_REVISION_2, generation: 1, replayed: false },
      },
    })).toBe(false)
    expect(isOperationLookup({
      context,
      reconciliation: { status: 'UNRESOLVED', head_revision_id: null, head_generation: 0, receipt: null },
    })).toBe(true)
    expect(isOperationLookup({
      context,
      reconciliation: {
        status: 'COMMITTED',
        head_revision_id: FIXTURE_REVISION_1,
        head_generation: 1,
        receipt: { operation_id: FIXTURE_OPERATION_A, revision_id: FIXTURE_REVISION_1, generation: 1, replayed: false },
      },
    })).toBe(true)
    expect(isOperationLookup({
      context,
      reconciliation: {
        status: 'COMMITTED',
        head_revision_id: FIXTURE_REVISION_2,
        head_generation: 2,
        receipt: { operation_id: FIXTURE_OPERATION_A, revision_id: FIXTURE_REVISION_1, generation: 1, replayed: false },
      },
    })).toBe(true)

    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      context,
      reconciliation: { status: 'UNRESOLVED', head_revision_id: FIXTURE_REVISION_1, head_generation: 0, receipt: null },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetch)
    const api = createReviewApi('job', () => 'token', vi.fn())
    await expect(api.lookup(FIXTURE_OPERATION_A, context.context_id)).rejects.toEqual(
      new ReviewApiError('INVALID_RESPONSE', 502),
    )
  })
})
