import type { Artifact, FindingDecisionRequest, RequestedChange, ReviewContext, UpdateReviewBody } from './contracts'

export const PENDING_SAVE_SCHEMA = 1
export const PENDING_SAVE_KEY_PREFIX = 'batchlens.pending-save.v1'
export const UUID_V4_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
export const CONTEXT_ID_PATTERN = /^[0-9a-f]{64}$/
const DECISION_ACTIONS = new Set(['KEEP_ORIGINAL', 'RESOLVED_AFTER_EDIT', 'ACKNOWLEDGED_LIMITATION'])
const PHASES = new Set(['uncertain', 'committed', 'superseded', 'mismatch', 'rejected'])

export type PendingSavePhase = 'uncertain' | 'committed' | 'superseded' | 'mismatch' | 'rejected'

export interface PendingSaveRecord {
  schema_version: 1
  context_id: string
  job_id: string
  actor: string
  baseline: Artifact
  operation_id: string
  body: string
  expected_revision: string | null
  base_generation: number
  phase: PendingSavePhase
  ambiguous: boolean
  message: string | null
}

export interface PendingSaveStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

export class PendingSaveStorageError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'PendingSaveStorageError'
  }
}

export function isUuidV4(value: unknown): value is string {
  return typeof value === 'string' && UUID_V4_PATTERN.test(value)
}

export function isContextId(value: unknown): value is string {
  return typeof value === 'string' && CONTEXT_ID_PATTERN.test(value)
}

export function isArtifactIdentity(value: unknown): value is Artifact {
  if (!value || typeof value !== 'object') return false
  const artifact = value as Artifact
  return typeof artifact.key === 'string' && artifact.key.length > 0
    && typeof artifact.version === 'string' && artifact.version.length > 0
    && typeof artifact.content_type === 'string' && artifact.content_type.length > 0
}

export function pendingSaveScope(apiBaseUrl = '', origin = typeof location === 'undefined' ? '' : location.origin): string {
  return `${origin}::${apiBaseUrl.replace(/\/$/, '')}`
}

export function pendingSaveKey(scope: string, contextId: string): string {
  return `${PENDING_SAVE_KEY_PREFIX}:${scope}:${contextId}`
}

export function sessionPendingStore(): PendingSaveStorage {
  return {
    getItem(key) {
      try {
        return sessionStorage.getItem(key)
      } catch (error) {
        throw new PendingSaveStorageError(error instanceof Error ? error.message : 'Browser storage is unavailable.')
      }
    },
    setItem(key, value) {
      try {
        sessionStorage.setItem(key, value)
      } catch (error) {
        throw new PendingSaveStorageError(error instanceof Error ? error.message : 'Browser storage could not be written.')
      }
    },
    removeItem(key) {
      try {
        sessionStorage.removeItem(key)
      } catch (error) {
        throw new PendingSaveStorageError(error instanceof Error ? error.message : 'Browser storage could not be updated.')
      }
    },
  }
}

export function memoryPendingStore(initial: Record<string, string> = {}): PendingSaveStorage {
  const data = new Map(Object.entries(initial))
  return {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => {
      data.set(key, value)
    },
    removeItem: (key) => {
      data.delete(key)
    },
  }
}

export function serializeSaveBody(
  expectedRevision: string | null,
  changes: RequestedChange[],
  decisions: FindingDecisionRequest[],
  operationId: string,
): string {
  return JSON.stringify({
    expected_revision: expectedRevision,
    changes,
    decisions,
    operation_id: operationId,
  } satisfies UpdateReviewBody)
}

function isRequestedChange(value: unknown): value is RequestedChange {
  if (!value || typeof value !== 'object') return false
  const change = value as RequestedChange
  return typeof change.node_id === 'string' && change.node_id.length > 0 && typeof change.text === 'string'
}

function isFindingDecision(value: unknown): value is FindingDecisionRequest {
  if (!value || typeof value !== 'object') return false
  const decision = value as FindingDecisionRequest
  if (typeof decision.finding_id !== 'string' || decision.finding_id.length === 0) return false
  if (!DECISION_ACTIONS.has(decision.action)) return false
  if (decision.note !== undefined && decision.note !== null && typeof decision.note !== 'string') return false
  if (decision.expected_region_hash !== undefined && decision.expected_region_hash !== null && typeof decision.expected_region_hash !== 'string') {
    return false
  }
  if (decision.replacement !== undefined && decision.replacement !== null && !isRequestedChange(decision.replacement)) return false
  return true
}

export function parseFrozenBody(body: string): UpdateReviewBody | null {
  try {
    const parsed: unknown = JSON.parse(body)
    if (!parsed || typeof parsed !== 'object') return null
    const value = parsed as UpdateReviewBody
    if (!isUuidV4(value.operation_id)) return null
    if (value.expected_revision !== null && !isUuidV4(value.expected_revision)) return null
    if (!Array.isArray(value.changes) || !value.changes.every(isRequestedChange)) return null
    if (!Array.isArray(value.decisions) || !value.decisions.every(isFindingDecision)) return null
    return value
  } catch {
    return null
  }
}

export function parsePendingRecord(raw: string): PendingSaveRecord | 'corrupt' {
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return 'corrupt'
    const value = parsed as PendingSaveRecord
    if (value.schema_version !== PENDING_SAVE_SCHEMA) return 'corrupt'
    if (!isContextId(value.context_id) || !isUuidV4(value.operation_id)) return 'corrupt'
    if (typeof value.body !== 'string' || typeof value.job_id !== 'string' || value.job_id.length === 0) return 'corrupt'
    if (typeof value.actor !== 'string' || value.actor.length === 0) return 'corrupt'
    if (!isArtifactIdentity(value.baseline)) return 'corrupt'
    if (value.expected_revision !== null && !isUuidV4(value.expected_revision)) return 'corrupt'
    if (!Number.isInteger(value.base_generation) || value.base_generation < 0) return 'corrupt'
    if (!PHASES.has(value.phase) || typeof value.ambiguous !== 'boolean') return 'corrupt'
    if (value.message !== null && typeof value.message !== 'string') return 'corrupt'
    const frozen = parseFrozenBody(value.body)
    if (!frozen) return 'corrupt'
    if (frozen.operation_id !== value.operation_id) return 'corrupt'
    if ((frozen.expected_revision ?? null) !== value.expected_revision) return 'corrupt'
    return value
  } catch {
    return 'corrupt'
  }
}

export function sameBaseline(left: Artifact, right: Artifact): boolean {
  return left.key === right.key && left.version === right.version && left.content_type === right.content_type
}

export function sameContext(record: PendingSaveRecord, context: ReviewContext): boolean {
  return (
    record.context_id === context.context_id
    && record.job_id === context.job_id
    && record.actor === context.actor
    && sameBaseline(record.baseline, context.baseline)
  )
}

export function recordsMatch(left: PendingSaveRecord, right: PendingSaveRecord): boolean {
  return (
    left.operation_id === right.operation_id
    && left.body === right.body
    && left.context_id === right.context_id
    && left.job_id === right.job_id
    && left.actor === right.actor
  )
}

export function readPendingRaw(store: PendingSaveStorage, scope: string, contextId: string): string | null {
  try {
    return store.getItem(pendingSaveKey(scope, contextId))
  } catch (error) {
    if (error instanceof PendingSaveStorageError) throw error
    throw new PendingSaveStorageError(error instanceof Error ? error.message : 'Browser storage is unavailable.')
  }
}

export function readPendingRecord(
  store: PendingSaveStorage,
  scope: string,
  contextId: string,
): PendingSaveRecord | 'corrupt' | null {
  const raw = readPendingRaw(store, scope, contextId)
  if (raw === null) return null
  const parsed = parsePendingRecord(raw)
  if (parsed === 'corrupt') return 'corrupt'
  if (parsed.context_id !== contextId) return 'corrupt'
  return parsed
}

export function writePendingRecord(store: PendingSaveStorage, scope: string, record: PendingSaveRecord): PendingSaveRecord {
  const key = pendingSaveKey(scope, record.context_id)
  const serialized = JSON.stringify(record)
  try {
    const existingRaw = store.getItem(key)
    if (existingRaw !== null) {
      const existing = parsePendingRecord(existingRaw)
      if (existing === 'corrupt') {
        throw new PendingSaveStorageError('A pending Save record is unreadable and was not replaced.')
      }
      if (existing.operation_id !== record.operation_id || existing.body !== record.body) {
        throw new PendingSaveStorageError('An unresolved Save already exists for this review and was not replaced.')
      }
    }
    store.setItem(key, serialized)
    const stored = store.getItem(key)
    if (stored !== serialized) throw new PendingSaveStorageError('The pending Save record could not be confirmed after writing.')
    const parsed = parsePendingRecord(stored)
    if (parsed === 'corrupt' || parsed.operation_id !== record.operation_id || parsed.body !== record.body) {
      throw new PendingSaveStorageError('The pending Save record could not be read back.')
    }
    return parsed
  } catch (error) {
    if (error instanceof PendingSaveStorageError) throw error
    throw new PendingSaveStorageError(error instanceof Error ? error.message : 'Browser storage could not be written.')
  }
}

export function removePendingRecord(store: PendingSaveStorage, scope: string, contextId: string): void {
  const key = pendingSaveKey(scope, contextId)
  try {
    store.removeItem(key)
    if (store.getItem(key) !== null) throw new PendingSaveStorageError('The pending Save record could not be removed.')
  } catch (error) {
    if (error instanceof PendingSaveStorageError) throw error
    throw new PendingSaveStorageError(error instanceof Error ? error.message : 'Browser storage could not be updated.')
  }
}

export function removeMatchingPendingRecord(store: PendingSaveStorage, scope: string, record: PendingSaveRecord): void {
  const key = pendingSaveKey(scope, record.context_id)
  try {
    const raw = store.getItem(key)
    if (raw === null) throw new PendingSaveStorageError('The pending Save record is no longer present.')
    const parsed = parsePendingRecord(raw)
    if (parsed === 'corrupt' || !recordsMatch(parsed, record)) {
      throw new PendingSaveStorageError('The stored Save record no longer matches this operation and was not removed.')
    }
    store.removeItem(key)
    if (store.getItem(key) !== null) throw new PendingSaveStorageError('The pending Save record could not be removed.')
  } catch (error) {
    if (error instanceof PendingSaveStorageError) throw error
    throw new PendingSaveStorageError(error instanceof Error ? error.message : 'Browser storage could not be updated.')
  }
}
