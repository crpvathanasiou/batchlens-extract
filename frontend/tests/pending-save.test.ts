import { describe, expect, it } from 'vitest'
import {
  memoryPendingStore,
  parsePendingRecord,
  pendingSaveKey,
  pendingSaveScope,
  readPendingRecord,
  removePendingRecord,
  serializeSaveBody,
  writePendingRecord,
  type PendingSaveRecord,
} from '../src/pendingSave'

const contextId = 'a'.repeat(64)

function sample(overrides: Partial<PendingSaveRecord> = {}): PendingSaveRecord {
  return {
    schema_version: 1,
    context_id: contextId,
    job_id: 'job',
    actor: 'alice',
    baseline: { key: 'document.json', version: '1', content_type: 'application/json' },
    operation_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    body: serializeSaveBody(null, [{ node_id: 'n-parent', text: 'saved' }], [], 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'),
    expected_revision: null,
    base_generation: 0,
    phase: 'uncertain',
    ambiguous: true,
    message: null,
    ...overrides,
  }
}

describe('pending save storage', () => {
  it('scopes keys by origin/api root and context, and isolates records', () => {
    expect(pendingSaveScope('', 'http://127.0.0.1:8766')).not.toBe(pendingSaveScope('', 'http://127.0.0.1:8765'))
    expect(pendingSaveKey('scope-a', contextId)).not.toBe(pendingSaveKey('scope-b', contextId))
    const store = memoryPendingStore()
    writePendingRecord(store, 'scope-a', sample())
    writePendingRecord(store, 'scope-b', sample({
      operation_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      context_id: 'b'.repeat(64),
      actor: 'bob',
      body: serializeSaveBody(null, [{ node_id: 'n-parent', text: 'saved' }], [], 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'),
    }))
    const retained = readPendingRecord(store, 'scope-a', contextId)
    expect(retained).not.toBe('corrupt')
    expect(retained).not.toBeNull()
    expect(retained && retained !== 'corrupt' ? retained.operation_id : null).toBe(
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    )
    expect(readPendingRecord(store, 'scope-a', 'b'.repeat(64))).toBeNull()
  })

  it('preserves a corrupt record instead of replacing it', () => {
    const store = memoryPendingStore({
      [pendingSaveKey('scope', contextId)]: '{not-json',
    })
    expect(readPendingRecord(store, 'scope', contextId)).toBe('corrupt')
    expect(parsePendingRecord('{not-json')).toBe('corrupt')
  })

  it('fails visibly when storage cannot write or confirm removal', async () => {
    const failing = {
      getItem: () => null,
      setItem: () => {
        throw new Error('quota')
      },
      removeItem: () => undefined,
    }
    expect(() => writePendingRecord(failing, 'scope', sample())).toThrow(/quota/)
    const sticky = memoryPendingStore()
    writePendingRecord(sticky, 'scope', sample())
    sticky.removeItem = () => undefined
    sticky.getItem = () => JSON.stringify(sample())
    expect(() => removePendingRecord(sticky, 'scope', contextId)).toThrow(/could not be removed/)
  })

  it('treats outer/body identity mismatch and invalid fields as corrupt and refuses overwrite', () => {
    const mismatched = JSON.stringify({
      ...sample(),
      operation_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      body: serializeSaveBody(null, [{ node_id: 'n-parent', text: 'saved' }], [], 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'),
    })
    expect(parsePendingRecord(mismatched)).toBe('corrupt')
    expect(parsePendingRecord(JSON.stringify({ ...sample(), base_generation: -1 }))).toBe('corrupt')
    expect(parsePendingRecord(JSON.stringify({ ...sample(), expected_revision: 'not-a-uuid' }))).toBe('corrupt')
    const store = memoryPendingStore({ [pendingSaveKey('scope', contextId)]: mismatched })
    expect(readPendingRecord(store, 'scope', contextId)).toBe('corrupt')
    expect(() => writePendingRecord(store, 'scope', sample())).toThrow(/unreadable and was not replaced/)
    expect(store.getItem(pendingSaveKey('scope', contextId))).toBe(mismatched)
  })

  it('refuses to replace a different unresolved operation under the same key', () => {
    const store = memoryPendingStore()
    writePendingRecord(store, 'scope', sample())
    expect(() => writePendingRecord(store, 'scope', sample({
      operation_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      body: serializeSaveBody(null, [{ node_id: 'n-parent', text: 'other' }], [], 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'),
    }))).toThrow(/already exists/)
    const retained = readPendingRecord(store, 'scope', contextId)
    expect(retained === 'corrupt' ? null : retained?.operation_id).toBe('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
  })

  it('treats outer/body expected-revision disagreement as corrupt', () => {
    const mismatched = JSON.stringify({
      ...sample(),
      expected_revision: '11111111-1111-4111-8111-111111111111',
    })
    expect(parsePendingRecord(mismatched)).toBe('corrupt')
  })

  it('leaves a different-key foreign record untouched while writing the current key', () => {
    const store = memoryPendingStore()
    const foreign = sample({
      context_id: 'b'.repeat(64),
      actor: 'bob',
      operation_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      body: serializeSaveBody(null, [{ node_id: 'n-parent', text: 'foreign' }], [], 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'),
    })
    writePendingRecord(store, 'scope', foreign)
    writePendingRecord(store, 'scope', sample())
    expect(readPendingRecord(store, 'scope', 'b'.repeat(64))).toEqual(expect.objectContaining({
      actor: 'bob',
      operation_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    }))
    expect(readPendingRecord(store, 'scope', contextId)).toEqual(expect.objectContaining({
      actor: 'alice',
      operation_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    }))
  })
})
