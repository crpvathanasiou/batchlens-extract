import { afterEach, describe, expect, it, vi } from 'vitest'
import { createReviewApi, ReviewApiError } from '../src/api'
import { reviewFixture } from './fixture'

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
})
