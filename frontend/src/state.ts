import type { JSONContent } from '@tiptap/core'
import { computed, reactive } from 'vue'
import { isConfirmedSaveState, isOperationLookup, isReviewContext, isReviewState, ReviewApiError, type ReviewApi } from './api'
import type {
  AttemptedWorkView,
  DecisionAction,
  FindingDecisionRequest,
  OperationLookup,
  RequestedChange,
  ReviewContext,
  ReviewFinding,
  ReviewStateResponse,
  SaveDispatch,
} from './contracts'
import { editableTextMap, headingLevel, projectPage, sparseChanges, structuralSignature, textContent, validateSkeleton } from './mapping'
import {
  PendingSaveStorageError,
  memoryPendingStore,
  isUuidV4,
  parseFrozenBody,
  pendingSaveScope,
  readPendingRecord,
  removeMatchingPendingRecord,
  sameBaseline,
  sameContext,
  serializeSaveBody,
  sessionPendingStore,
  writePendingRecord,
  type PendingSaveRecord,
  type PendingSaveStorage,
} from './pendingSave'

export const TOLERANCE_AMBIGUITY_CODE = 'POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY'

const ACTION_LABELS: Record<DecisionAction, string> = {
  KEEP_ORIGINAL: 'Keep original',
  RESOLVED_AFTER_EDIT: 'Mark resolved after edit',
  ACKNOWLEDGED_LIMITATION: 'Acknowledge limitation',
}

export function unresolvedToleranceNodeIds(findings: ReviewFinding[]): string[] {
  const ids: string[] = []
  for (const finding of findings) {
    if (finding.code !== TOLERANCE_AMBIGUITY_CODE) continue
    if (finding.decision?.region_hash === finding.region_hash) continue
    ids.push(...finding.node_ids)
  }
  return [...new Set(ids)]
}

export interface ReviewStateOptions {
  pendingStore?: PendingSaveStorage
  scope?: string
}

export interface ReviewWorkspaceState {
  server: ReviewStateResponse | null
  context: ReviewContext | null
  drafts: Record<number, JSONContent>
  baselines: Record<number, Map<string, string>>
  skeletons: Record<number, unknown>
  unsupported: Record<number, string[]>
  decisions: Record<string, FindingDecisionRequest>
  loading: boolean
  pending: boolean
  error: string | null
  contentError: string | null
  saveStatus: 'SAVED' | 'SAVING' | 'UNKNOWN' | 'BLOCKED'
  conflict: boolean
  activePage: number
  pendingRecord: PendingSaveRecord | null
  corruptPending: boolean
  workspaceGeneration: number
  knownCommit: boolean
  uncertainAttempt: boolean
}

type ActionKind = 'load' | 'save' | 'retry' | 'check' | 'dispose' | 'approve'
interface ActionReservation {
  id: number
  kind: ActionKind
  generation: number
}

interface PreparedProjection {
  drafts: Record<number, JSONContent>
  baselines: Record<number, Map<string, string>>
  skeletons: Record<number, unknown>
  unsupported: Record<number, string[]>
  activePage: number
}

export function createReviewState(api: ReviewApi, options: ReviewStateOptions = {}) {
  const store = options.pendingStore ?? (typeof sessionStorage === 'undefined' ? memoryPendingStore() : sessionPendingStore())
  const scope = options.scope ?? pendingSaveScope()
  const state = reactive<ReviewWorkspaceState>({
    server: null,
    context: null,
    drafts: {},
    baselines: {},
    skeletons: {},
    unsupported: {},
    decisions: {},
    loading: false,
    pending: false,
    error: null,
    contentError: null,
    saveStatus: 'SAVED',
    conflict: false,
    activePage: 1,
    pendingRecord: null,
    corruptPending: false,
    workspaceGeneration: 0,
    knownCommit: false,
    uncertainAttempt: false,
  })

  let actionSeq = 0
  let activeAction: ActionReservation | null = null

  const changes = computed(() =>
    Object.entries(state.drafts).flatMap(([page, draft]) =>
      sparseChanges(state.baselines[Number(page)] ?? new Map(), draft),
    ),
  )
  const blocked = computed(() => Boolean(state.pendingRecord || state.corruptPending || state.pending || activeAction))
  const dirty = computed(
    () => blocked.value || changes.value.length > 0 || Object.keys(state.decisions).length > 0,
  )
  const unsupported = computed(() => Object.values(state.unsupported).flat())
  const attemptedWork = computed(() => describeAttemptedWork(state.pendingRecord, state.server))

  function bumpGeneration(): number {
    state.workspaceGeneration += 1
    return state.workspaceGeneration
  }

  function takeAction(kind: ActionKind, generation = state.workspaceGeneration): number {
    actionSeq += 1
    activeAction = { id: actionSeq, kind, generation }
    state.pending = true
    return actionSeq
  }

  function reserveExclusive(kind: ActionKind): number | null {
    if (activeAction) return null
    return takeAction(kind)
  }

  function release(actionId: number) {
    if (activeAction?.id !== actionId) return
    activeAction = null
    state.pending = false
  }

  function isLive(actionId: number, generation: number, record?: PendingSaveRecord): boolean {
    if (activeAction?.id !== actionId) return false
    if (generation !== state.workspaceGeneration) return false
    if (record && state.pendingRecord && state.pendingRecord.operation_id !== record.operation_id) return false
    if (record && state.context && state.context.context_id !== record.context_id) return false
    return true
  }

  function mutationsFrozen(): boolean {
    return Boolean(state.pendingRecord || state.corruptPending || state.pending || activeAction)
  }

  function prepareProjection(server: ReviewStateResponse): PreparedProjection {
    if (!isReviewState(server) || !server.document.pages.length) {
      throw new ReviewApiError('INVALID_RESPONSE', 502)
    }
    const drafts: Record<number, JSONContent> = {}
    const baselines: Record<number, Map<string, string>> = {}
    const skeletons: Record<number, unknown> = {}
    const unsupportedPages: Record<number, string[]> = {}
    for (const page of server.document.pages) {
      const projection = projectPage(server, page.number)
      drafts[page.number] = projection.doc
      baselines[page.number] = projection.baselineTexts
      skeletons[page.number] = structuralSignature(projection.doc)
      unsupportedPages[page.number] = projection.unsupported
    }
    return {
      drafts,
      baselines,
      skeletons,
      unsupported: unsupportedPages,
      activePage: Math.min(Math.max(state.activePage, 1), Math.max(server.document.pages.length, 1)),
    }
  }

  function applyPrepared(server: ReviewStateResponse, prepared: PreparedProjection, freeze = false) {
    state.server = server
    state.drafts = prepared.drafts
    state.baselines = prepared.baselines
    state.skeletons = prepared.skeletons
    state.unsupported = prepared.unsupported
    if (!freeze) state.decisions = {}
    state.activePage = prepared.activePage
    state.contentError = null
    if (!freeze) {
      state.conflict = false
      if (!state.pendingRecord && !state.corruptPending) state.saveStatus = 'SAVED'
    }
  }

  function projectServer(server: ReviewStateResponse, freeze = false) {
    applyPrepared(server, prepareProjection(server), freeze)
  }

  function canApplyState(next: ReviewStateResponse): string | null {
    const current = state.server
    if (!current) return null
    if (next.generation < current.generation) return 'stale'
    if (
      next.generation === current.generation
      && next.revision_id !== current.revision_id
      && current.revision_id !== null
      && next.revision_id !== null
    ) {
      return 'generation-conflict'
    }
    return null
  }

  function inspectStored(contextId: string): PendingSaveRecord | 'corrupt' | null {
    return readPendingRecord(store, scope, contextId)
  }

  function adoptCorrupt(message: string) {
    state.corruptPending = true
    state.pendingRecord = null
    state.error = message
    recoveryStatus()
  }

  function persistRecord(record: PendingSaveRecord, actionId: number, generation: number): PendingSaveRecord | null {
    if (!isLive(actionId, generation, state.pendingRecord ?? record)) return null
    const stored = writePendingRecord(store, scope, record)
    if (!isLive(actionId, generation, stored)) return null
    state.pendingRecord = stored
    state.corruptPending = false
    return stored
  }

  function markRecord(record: PendingSaveRecord, patch: Partial<PendingSaveRecord>, actionId: number, generation: number) {
    if (!isLive(actionId, generation, record)) return
    if (state.pendingRecord && state.pendingRecord.operation_id !== record.operation_id) return
    const next = { ...record, ...patch }
    try {
      persistRecord(next, actionId, generation)
    } catch (error) {
      if (!isLive(actionId, generation, record)) return
      state.pendingRecord = next
      state.corruptPending = false
      const detail = error instanceof Error ? error.message : 'Browser storage could not be updated.'
      state.error = next.ambiguous ? `Save status unknown. ${detail}` : detail
      recoveryStatus(next)
    }
  }

  function rememberUncertain(record: PendingSaveRecord, message: string, actionId: number, generation: number) {
    if (!isLive(actionId, generation, record)) return
    state.uncertainAttempt = true
    markRecord(record, { phase: 'uncertain', ambiguous: true, message }, actionId, generation)
    if (!isLive(actionId, generation, record)) return
    if (state.pendingRecord?.operation_id === record.operation_id) {
      state.pendingRecord = { ...state.pendingRecord, phase: 'uncertain', ambiguous: true }
    }
    if (!state.error || !/Save status unknown|could not be updated/i.test(state.error)) {
      state.error = 'Save status unknown. Check save status or retry the same save.'
    }
    recoveryStatus()
  }

  function recoveryStatus(record: PendingSaveRecord | null = state.pendingRecord) {
    if (state.corruptPending) {
      state.saveStatus = 'BLOCKED'
      return
    }
    if (!record && !state.knownCommit) {
      state.saveStatus = 'SAVED'
      return
    }
    if (record?.phase === 'committed' || state.knownCommit) {
      state.saveStatus = 'BLOCKED'
      return
    }
    state.saveStatus = record?.phase === 'uncertain' ? 'UNKNOWN' : 'BLOCKED'
  }

  function describeCommitLocalFailure(message: string) {
    state.knownCommit = true
    state.error = message
    if (state.pendingRecord) {
      state.pendingRecord = { ...state.pendingRecord, phase: 'committed', ambiguous: false, message }
    }
    recoveryStatus()
  }

  async function requireContext(actionId: number, generation: number, expectedContextId?: string): Promise<ReviewContext | null> {
    const context = await api.context()
    if (!isLive(actionId, generation)) return null
    if (!isReviewContext(context)) throw new ReviewApiError('INVALID_RESPONSE', 502)
    if (expectedContextId && context.context_id !== expectedContextId) throw new ReviewApiError('REVIEW_CONTEXT_CHANGED', 409)
    if (state.context && context.context_id !== state.context.context_id) throw new ReviewApiError('REVIEW_CONTEXT_CHANGED', 409)
    if (state.context && context.actor !== state.context.actor) throw new ReviewApiError('REVIEW_CONTEXT_CHANGED', 409)
    if (!isLive(actionId, generation)) return null
    state.context = context
    return context
  }

  async function contextStillMatches(
    actionId: number,
    generation: number,
    record: PendingSaveRecord,
  ): Promise<ReviewContext | null> {
    try {
      const context = await requireContext(actionId, generation, record.context_id)
      if (!isLive(actionId, generation, record)) return null
      if (!context || !sameContext(record, context)) {
        if (isLive(actionId, generation, record)) {
          state.error = 'The review context changed. The pending Save was kept and was not applied here.'
          recoveryStatus(record)
        }
        return null
      }
      return context
    } catch (error) {
      if (!isLive(actionId, generation, record)) return null
      state.error = error instanceof Error
        ? `${error.message === 'REVIEW_CONTEXT_CHANGED' ? 'The review context changed' : error.message}. The pending Save was kept and was not applied here.`
        : 'The review context could not be verified. The pending Save was kept and was not applied here.'
      recoveryStatus(record)
      return null
    }
  }

  function stateMatchesRecord(next: ReviewStateResponse, record: PendingSaveRecord, context: ReviewContext): boolean {
    if (!sameBaseline(context.baseline, next.catalogue.baseline)) return false
    if (!sameBaseline(record.baseline, next.catalogue.baseline)) return false
    if (next.revision && next.revision.job_id !== record.job_id) return false
    return context.job_id === record.job_id
  }

  function coherentPendingBase(record: PendingSaveRecord): boolean {
    if (record.expected_revision === null) return record.base_generation === 0
    return isUuidV4(record.expected_revision) && Number.isInteger(record.base_generation) && record.base_generation >= 1
  }

  function provesSuperseded(lookup: OperationLookup, record: PendingSaveRecord): boolean {
    if (lookup.reconciliation.status !== 'UNRESOLVED') return false
    const headId = lookup.reconciliation.head_revision_id
    if (!headId || headId === record.expected_revision) return false
    if (!coherentPendingBase(record)) return false
    return lookup.reconciliation.head_generation > record.base_generation
  }

  function dispatchFrom(record: PendingSaveRecord): SaveDispatch {
    return { operationId: record.operation_id, contextId: record.context_id, body: record.body }
  }

  function usableLookup(value: unknown, record: PendingSaveRecord): OperationLookup | null {
    if (!isOperationLookup(value)) return null
    if (!sameContext(record, value.context)) return null
    if (value.reconciliation.receipt && value.reconciliation.receipt.operation_id !== record.operation_id) return null
    return value
  }

  async function retireAfterCommit(
    next: ReviewStateResponse,
    generation: number,
    actionId: number,
    record: PendingSaveRecord,
  ): Promise<boolean> {
    if (!isLive(actionId, generation, record)) return false
    try {
      const context = await requireContext(actionId, generation, record.context_id)
      if (!isLive(actionId, generation, record)) return false
      if (!context || !sameContext(record, context)) {
        state.error = 'The review context changed. The pending Save was kept and was not applied here.'
        recoveryStatus(record)
        return false
      }
      if (!isConfirmedSaveState(next)) {
        markRecord(record, { phase: 'uncertain', ambiguous: true, message: 'Save status unknown.' }, actionId, generation)
        state.error = 'Save status unknown. Check save status or retry the same save.'
        recoveryStatus()
        return false
      }
      if (!sameBaseline(context.baseline, next.catalogue.baseline)) {
        markRecord(record, { phase: 'uncertain', ambiguous: true, message: 'Save status unknown.' }, actionId, generation)
        state.error = 'Save status unknown. Check save status or retry the same save.'
        recoveryStatus()
        return false
      }
      const stale = canApplyState(next)
      if (stale) {
        state.error = stale === 'generation-conflict'
          ? 'The server returned a conflicting review generation. The pending Save was kept.'
          : 'The server returned an older review generation. The pending Save was kept.'
        recoveryStatus(record)
        return false
      }
      let prepared: PreparedProjection
      try {
        prepared = prepareProjection(next)
      } catch (error) {
        describeCommitLocalFailure(
          error instanceof Error
            ? `This Save committed, but the review could not be shown: ${error.message}`
            : 'This Save committed, but the review could not be shown.',
        )
        return false
      }
      state.knownCommit = true
      applyPrepared(next, prepared)
      try {
        removeMatchingPendingRecord(store, scope, record)
        if (isLive(actionId, generation) && (state.pendingRecord?.operation_id === record.operation_id || !state.pendingRecord)) {
          state.pendingRecord = null
          state.knownCommit = false
          state.uncertainAttempt = false
          state.conflict = false
          state.saveStatus = 'SAVED'
          state.error = null
        }
        return true
      } catch (error) {
        try {
          markRecord(record, {
            phase: 'committed',
            ambiguous: false,
            message: error instanceof Error ? error.message : 'The pending Save record could not be cleared.',
          }, actionId, generation)
        } catch {
          if (state.pendingRecord?.operation_id === record.operation_id) {
            state.pendingRecord = { ...record, phase: 'committed', ambiguous: false, message: 'The pending Save record could not be cleared.' }
          }
        }
        describeCommitLocalFailure(
          'This Save committed, but the recovery record could not be cleared. Retry the same save; it will not create a new revision.',
        )
        return false
      }
    } catch (error) {
      if (!isLive(actionId, generation, record)) return false
      if (state.knownCommit) {
        describeCommitLocalFailure(
          error instanceof Error ? error.message : 'This Save committed, but local recovery could not be completed.',
        )
        return false
      }
      throw error
    }
  }

  async function replayExact(record: PendingSaveRecord, generation: number, actionId: number): Promise<boolean> {
    const parsed = parseFrozenBody(record.body)
    if (!parsed) {
      markRecord(record, { phase: 'uncertain', ambiguous: true, message: 'The stored Save body is unreadable.' }, actionId, generation)
      recoveryStatus()
      return false
    }
    const context = await requireContext(actionId, generation, record.context_id)
    if (!context || !isLive(actionId, generation, record) || !sameContext(record, context)) return false
    const next = await api.save(
      parsed.expected_revision ?? null,
      parsed.changes,
      parsed.decisions,
      dispatchFrom(record),
    )
    if (!isLive(actionId, generation, record)) return false
    return retireAfterCommit(next, generation, actionId, record)
  }

  async function handleConflict(record: PendingSaveRecord, generation: number, actionId: number): Promise<void> {
    if (!isLive(actionId, generation, record)) return
    state.conflict = true
    try {
      const lookup = usableLookup(await api.lookup(record.operation_id, record.context_id), record)
      if (!isLive(actionId, generation, record)) return
      if (!lookup) {
        rememberUncertain(record, 'Save status unknown after a review conflict.', actionId, generation)
        return
      }
      if (lookup.reconciliation.status === 'COMMITTED') {
        await confirmCommitted(record, generation, actionId)
        return
      }
      if (provesSuperseded(lookup, record)) {
        const verified = await contextStillMatches(actionId, generation, record)
        if (!verified) return
        markRecord(record, {
          phase: 'superseded',
          ambiguous: false,
          message: 'The review changed before this Save could commit.',
        }, actionId, generation)
        if (!isLive(actionId, generation, record)) return
        state.error = 'Review conflict. This Save did not commit. Discard the attempted Save to load the current review, then save again if needed.'
        recoveryStatus()
        return
      }
      rememberUncertain(record, 'Save status unknown after a review conflict.', actionId, generation)
    } catch {
      if (!isLive(actionId, generation, record)) return
      rememberUncertain(record, 'Save status unknown after a review conflict.', actionId, generation)
    }
  }

  async function handleMismatch(record: PendingSaveRecord, generation: number, actionId: number): Promise<void> {
    try {
      const lookup = usableLookup(await api.lookup(record.operation_id, record.context_id), record)
      if (!isLive(actionId, generation, record)) return
      if (!lookup || lookup.reconciliation.status !== 'COMMITTED') {
        rememberUncertain(record, 'Save status unknown after a fingerprint mismatch.', actionId, generation)
        return
      }
      const next = await api.load()
      if (!isLive(actionId, generation, record)) return
      const verified = await contextStillMatches(actionId, generation, record)
      if (!verified) return
      if (!isReviewState(next) || !stateMatchesRecord(next, record, verified)) {
        rememberUncertain(record, 'Save status unknown after a fingerprint mismatch.', actionId, generation)
        return
      }
      if (canApplyState(next) === null) {
        try {
          applyPrepared(next, prepareProjection(next), true)
        } catch {
          // Keep the current editor projection if the new one cannot be prepared.
        }
      }
    } catch {
      if (!isLive(actionId, generation, record)) return
      rememberUncertain(record, 'Save status unknown after a fingerprint mismatch.', actionId, generation)
      return
    }
    if (!isLive(actionId, generation, record)) return
    markRecord(record, {
      phase: 'mismatch',
      ambiguous: false,
      message: 'This Save ID is already bound to different content.',
    }, actionId, generation)
    if (!isLive(actionId, generation, record)) return
    state.error = 'This Save does not match the committed operation. Discard the attempted Save to continue, then save your current edits as a new Save if needed.'
    recoveryStatus()
  }

  async function confirmCommitted(record: PendingSaveRecord, generation: number, actionId: number): Promise<boolean> {
    try {
      return await replayExact(record, generation, actionId)
    } catch (error) {
      if (!isLive(actionId, generation, record)) return false
      if (error instanceof ReviewApiError && error.code === 'SAVE_OPERATION_MISMATCH') {
        await handleMismatch(record, generation, actionId)
        return false
      }
      throw error
    }
  }

  async function recoverExisting(record: PendingSaveRecord, generation: number, actionId: number): Promise<void> {
    if (!isLive(actionId, generation, record)) return
    recoveryStatus(record)
    state.error = record.message || 'Save status unknown.'
    if (record.phase === 'superseded' || record.phase === 'mismatch' || record.phase === 'rejected') {
      return
    }
    try {
      const lookup = usableLookup(await api.lookup(record.operation_id, record.context_id), record)
      if (!isLive(actionId, generation, record)) return
      if (!lookup) {
        if (state.knownCommit || record.phase === 'committed') {
          describeCommitLocalFailure('Save status unknown after a committed Save. The recovery record was kept.')
          return
        }
        rememberUncertain(record, 'Save status unknown.', actionId, generation)
        return
      }
      if (lookup.reconciliation.status === 'COMMITTED') {
        await confirmCommitted(record, generation, actionId)
        return
      }
      if (state.knownCommit || record.phase === 'committed') {
        describeCommitLocalFailure('Save status unknown after a committed Save. The recovery record was kept.')
        return
      }
      rememberUncertain(record, 'Save status unknown.', actionId, generation)
    } catch {
      if (!isLive(actionId, generation, record)) return
      if (state.knownCommit || record.phase === 'committed') {
        describeCommitLocalFailure('Save status unknown after a committed Save. The recovery record was kept.')
        return
      }
      rememberUncertain(record, 'Save status unknown.', actionId, generation)
    }
  }

  async function load() {
    const generation = bumpGeneration()
    const actionId = takeAction('load', generation)
    state.loading = true
    state.error = null
    try {
      const first = await api.context()
      if (!isLive(actionId, generation)) return
      if (!isReviewContext(first)) throw new ReviewApiError('INVALID_RESPONSE', 502)
      const server = await api.load()
      if (!isLive(actionId, generation)) return
      if (!isReviewState(server)) throw new ReviewApiError('INVALID_RESPONSE', 502)
      const second = await api.context()
      if (!isLive(actionId, generation)) return
      if (!isReviewContext(second) || first.context_id !== second.context_id || first.actor !== second.actor) {
        throw new ReviewApiError('REVIEW_CONTEXT_CHANGED', 409)
      }
      if (!sameBaseline(second.baseline, server.catalogue.baseline)) {
        throw new ReviewApiError('REVIEW_CONTEXT_CHANGED', 409)
      }
      state.context = second
      let stored: PendingSaveRecord | 'corrupt' | null = null
      try {
        stored = inspectStored(second.context_id)
      } catch (error) {
        adoptCorrupt(error instanceof Error ? error.message : 'Browser storage is unavailable.')
        projectServer(server, true)
        return
      }
      if (stored === 'corrupt' || (stored && !sameContext(stored, second))) {
        adoptCorrupt(
          stored === 'corrupt'
            ? 'A pending Save record is unreadable. Recovery is blocked for this review until the record can be repaired outside this session.'
            : 'A pending Save record does not match this review and was not replaced. Recovery is blocked for this review.',
        )
        projectServer(server, true)
        return
      }
      if (stored) {
        state.pendingRecord = stored
        state.knownCommit = stored.phase === 'committed'
        state.uncertainAttempt = stored.phase !== 'rejected'
        projectServer(server, true)
        await recoverExisting(stored, generation, actionId)
        return
      }
      state.pendingRecord = null
      state.corruptPending = false
      state.knownCommit = false
      state.uncertainAttempt = false
      projectServer(server)
    } catch (error) {
      if (!isLive(actionId, generation)) return
      state.error = error instanceof Error ? error.message : 'Unable to load the review.'
    } finally {
      if (isLive(actionId, generation)) state.loading = false
      release(actionId)
    }
  }

  function validationErrors(): string[] {
    return [
      ...unsupported.value,
      ...Object.entries(state.drafts).flatMap(([page, draft]) =>
        validateSkeleton(state.skeletons[Number(page)], draft),
      ),
    ]
  }

  function currentTexts(): Map<string, string> {
    const texts = new Map<string, string>()
    for (const draft of Object.values(state.drafts)) {
      for (const [nodeId, text] of editableTextMap(draft)) texts.set(nodeId, text)
    }
    return texts
  }

  function invalidateDivergedReplacements(texts = currentTexts()) {
    for (const [findingId, decision] of Object.entries(state.decisions)) {
      const replacement = decision.replacement
      if (!replacement) continue
      if (texts.get(replacement.node_id) !== replacement.text) delete state.decisions[findingId]
    }
  }

  function saveChanges(): RequestedChange[] {
    const replacements = new Map(
      Object.values(state.decisions)
        .filter((decision) => decision.replacement)
        .map((decision) => [decision.replacement!.node_id, decision.replacement!.text]),
    )
    return changes.value.filter((change) => replacements.get(change.node_id) !== change.text)
  }

  function adoptExisting(existing: PendingSaveRecord | 'corrupt', actionId: number, generation: number) {
    if (!isLive(actionId, generation)) return
    if (existing === 'corrupt') {
      adoptCorrupt('A pending Save record is unreadable and was not replaced. The draft was kept and was not sent.')
      return
    }
    state.pendingRecord = existing
    state.corruptPending = false
    state.uncertainAttempt = true
    state.error = 'A pending Save is already in progress for this review. Check save status or retry the same save.'
    recoveryStatus(existing)
  }

  async function dispatchRecord(record: PendingSaveRecord, generation: number, actionId: number): Promise<boolean> {
    const parsed = parseFrozenBody(record.body)
    if (!parsed) {
      markRecord(record, { phase: 'uncertain', ambiguous: true, message: 'The stored Save body is unreadable.' }, actionId, generation)
      recoveryStatus()
      return false
    }
    state.saveStatus = 'SAVING'
    state.error = null
    try {
      const next = await api.save(
        parsed.expected_revision ?? null,
        parsed.changes,
        parsed.decisions,
        dispatchFrom(record),
      )
      if (!isLive(actionId, generation, record)) return false
      return await retireAfterCommit(next, generation, actionId, record)
    } catch (error) {
      if (!isLive(actionId, generation, record)) return false
      if (state.knownCommit) {
        describeCommitLocalFailure(
          error instanceof Error ? error.message : 'This Save committed, but local recovery could not be completed.',
        )
        return false
      }
      if (error instanceof ReviewApiError && error.code === 'REVIEW_CONFLICT') {
        await handleConflict(record, generation, actionId)
        return false
      }
      if (error instanceof ReviewApiError && error.code === 'SAVE_OPERATION_MISMATCH') {
        await handleMismatch(record, generation, actionId)
        return false
      }
      if (
        error instanceof ReviewApiError
        && error.code === 'INVALID_REVIEW'
        && error.status === 422
        && !record.ambiguous
        && !state.uncertainAttempt
      ) {
        markRecord(record, {
          phase: 'rejected',
          ambiguous: false,
          message: 'The server rejected this Save.',
        }, actionId, generation)
        if (!isLive(actionId, generation, record)) return false
        state.error = 'The server rejected this Save. Discard the attempted Save to continue editing, then save again if needed.'
        recoveryStatus()
        return false
      }
      rememberUncertain(
        record,
        error instanceof Error ? error.message : 'Save status unknown.',
        actionId,
        generation,
      )
      return false
    }
  }

  async function save(force = false): Promise<boolean> {
    if (!state.server || mutationsFrozen()) return false
    const invalid = validationErrors()
    if (invalid.length) {
      state.contentError = invalid[0]
      return false
    }
    invalidateDivergedReplacements()
    if (!force && !dirty.value) return true
    const generation = state.workspaceGeneration
    const actionId = reserveExclusive('save')
    if (actionId == null) return false
    try {
      if (state.context) {
        const existing = inspectStored(state.context.context_id)
        if (existing === 'corrupt' || existing) {
          adoptExisting(existing, actionId, generation)
          return false
        }
      }
      const context = await requireContext(actionId, generation)
      if (!context || !isLive(actionId, generation) || !state.server) return false
      if (context.job_id && state.server.revision?.job_id && context.job_id !== state.server.revision.job_id) {
        state.error = 'The review context does not match this document.'
        state.saveStatus = 'SAVED'
        return false
      }
      if (!sameBaseline(context.baseline, state.server.catalogue.baseline)) {
        state.error = 'The review baseline does not match this document.'
        state.saveStatus = 'SAVED'
        return false
      }
      const existing = inspectStored(context.context_id)
      if (existing === 'corrupt' || existing) {
        adoptExisting(existing, actionId, generation)
        return false
      }
      const operationId = crypto.randomUUID()
      const payload = saveChanges()
      const decisions = Object.values(state.decisions)
      const body = serializeSaveBody(state.server.revision_id, payload, decisions, operationId)
      const record = persistRecord({
        schema_version: 1,
        context_id: context.context_id,
        job_id: context.job_id,
        actor: context.actor,
        baseline: context.baseline,
        operation_id: operationId,
        body,
        expected_revision: state.server.revision_id,
        base_generation: state.server.generation,
        phase: 'uncertain',
        ambiguous: false,
        message: null,
      }, actionId, generation)
      if (!record) return false
      return await dispatchRecord(record, generation, actionId)
    } catch (error) {
      if (!isLive(actionId, generation)) return false
      if (state.knownCommit || state.pendingRecord?.phase === 'committed') {
        describeCommitLocalFailure(
          'This Save committed, but the recovery record could not be cleared. Retry the same save; it will not create a new revision.',
        )
        return false
      }
      const contextId = state.context?.context_id
      if (contextId && error instanceof PendingSaveStorageError) {
        const retained = inspectStored(contextId)
        if (retained === 'corrupt' || retained) {
          adoptExisting(retained, actionId, generation)
          return false
        }
        state.error = `${error.message} The draft was kept and was not sent.`
        state.saveStatus = 'SAVED'
        return false
      }
      if (error instanceof PendingSaveStorageError) {
        state.error = `${error.message} The draft was kept and was not sent.`
        state.saveStatus = 'SAVED'
        return false
      }
      state.error = error instanceof Error ? error.message : 'Unable to prepare the save.'
      if (!state.pendingRecord) state.saveStatus = 'SAVED'
      else recoveryStatus()
      return false
    } finally {
      release(actionId)
    }
  }

  async function retrySameSave(): Promise<boolean> {
    const record = state.pendingRecord
    if (!record || !state.server || state.corruptPending || activeAction) return false
    if (record.phase === 'superseded' || record.phase === 'mismatch' || record.phase === 'rejected') return false
    const generation = state.workspaceGeneration
    const actionId = reserveExclusive('retry')
    if (actionId == null) return false
    try {
      const context = await requireContext(actionId, generation, record.context_id)
      if (!context || !isLive(actionId, generation, record) || !sameContext(record, context)) {
        if (isLive(actionId, generation)) state.error = 'This Save belongs to another review context and was not sent.'
        return false
      }
      return await dispatchRecord(record, generation, actionId)
    } catch (error) {
      if (!isLive(actionId, generation, record)) return false
      if (state.knownCommit || record.phase === 'committed') {
        describeCommitLocalFailure(
          error instanceof Error ? error.message : 'This Save committed, but local recovery could not be completed.',
        )
        return false
      }
      rememberUncertain(
        record,
        error instanceof Error ? error.message : 'Save status unknown.',
        actionId,
        generation,
      )
      return false
    } finally {
      release(actionId)
    }
  }

  async function checkSaveStatus(): Promise<void> {
    const record = state.pendingRecord
    if (!record || state.corruptPending || activeAction) return
    const generation = state.workspaceGeneration
    const actionId = reserveExclusive('check')
    if (actionId == null) return
    try {
      const context = await requireContext(actionId, generation, record.context_id)
      if (!context || !isLive(actionId, generation, record) || !sameContext(record, context)) {
        if (isLive(actionId, generation)) state.error = 'This Save belongs to another review context.'
        return
      }
      await recoverExisting(record, generation, actionId)
    } catch (error) {
      if (!isLive(actionId, generation, record)) return
      if (state.knownCommit || record.phase === 'committed') {
        describeCommitLocalFailure(
          error instanceof Error ? error.message : 'This Save committed, but local recovery could not be completed.',
        )
        return
      }
      rememberUncertain(
        record,
        error instanceof Error ? error.message : 'Save status unknown.',
        actionId,
        generation,
      )
    } finally {
      release(actionId)
    }
  }

  async function acknowledgeAttemptedSave(): Promise<void> {
    const record = state.pendingRecord
    if (!record || state.corruptPending || activeAction) return
    if (record.phase !== 'superseded' && record.phase !== 'mismatch' && record.phase !== 'rejected') return
    const generation = state.workspaceGeneration
    const actionId = reserveExclusive('dispose')
    if (actionId == null) return
    try {
      const context = await requireContext(actionId, generation, record.context_id)
      if (!context || !isLive(actionId, generation, record) || !sameContext(record, context)) return
      const next = await api.load()
      if (!isLive(actionId, generation, record)) return
      const verified = await contextStillMatches(actionId, generation, record)
      if (!verified) return
      if (!isReviewState(next)) throw new ReviewApiError('INVALID_RESPONSE', 502)
      if (!stateMatchesRecord(next, record, verified)) {
        state.error = 'The current review does not match this Save. The attempted Save was kept.'
        recoveryStatus(record)
        return
      }
      const stale = canApplyState(next)
      if (stale === 'stale' || stale === 'generation-conflict') {
        state.error = 'The current review could not be loaded without replacing newer work. The attempted Save was kept.'
        recoveryStatus(record)
        return
      }
      applyPrepared(next, prepareProjection(next))
      removeMatchingPendingRecord(store, scope, record)
      if (isLive(actionId, generation) && state.pendingRecord?.operation_id === record.operation_id) {
        state.pendingRecord = null
        state.knownCommit = false
        state.uncertainAttempt = false
        state.conflict = false
        state.error = null
        state.saveStatus = 'SAVED'
      }
    } catch (error) {
      if (!isLive(actionId, generation, record)) return
      state.error = error instanceof Error ? error.message : 'The attempted Save could not be cleared.'
      recoveryStatus()
    } finally {
      release(actionId)
    }
  }

  async function approvePage(): Promise<void> {
    if (mutationsFrozen() || !state.server) return
    if (!(await save(state.server.revision_id === null))) return
    if (mutationsFrozen() || !state.server) return
    const revision = state.server.revision_id
    const contextId = state.context?.context_id
    if (!revision) return
    const generation = state.workspaceGeneration
    const actionId = reserveExclusive('approve')
    if (actionId == null) return
    try {
      const next = await api.approvePage(state.activePage, revision, contextId)
      if (!isLive(actionId, generation)) return
      if (isReviewState(next) && canApplyState(next) !== 'stale' && canApplyState(next) !== 'generation-conflict') {
        applyPrepared(next, prepareProjection(next))
        state.error = null
      }
    } catch (error) {
      if (!isLive(actionId, generation)) return
      if (error instanceof ReviewApiError && error.code === 'REVIEW_CONFLICT') {
        state.conflict = true
        state.error = 'The server review changed. Your draft is preserved; reload only after reconciling your work.'
      } else {
        state.error = error instanceof Error ? error.message : 'Unable to approve the page.'
      }
    } finally {
      release(actionId)
    }
  }

  async function approveDocument(): Promise<void> {
    if (mutationsFrozen() || !state.server) return
    if (!(await save(state.server.revision_id === null))) return
    if (mutationsFrozen() || !state.server) return
    const revision = state.server.revision_id
    const contextId = state.context?.context_id
    if (!revision) return
    const generation = state.workspaceGeneration
    const actionId = reserveExclusive('approve')
    if (actionId == null) return
    try {
      const next = await api.approve(revision, contextId)
      if (!isLive(actionId, generation)) return
      if (isReviewState(next) && canApplyState(next) !== 'stale' && canApplyState(next) !== 'generation-conflict') {
        applyPrepared(next, prepareProjection(next))
        state.error = null
      }
    } catch (error) {
      if (!isLive(actionId, generation)) return
      if (error instanceof ReviewApiError && error.code === 'REVIEW_CONFLICT') {
        state.conflict = true
        state.error = 'The server review changed. Your draft is preserved; reload only after reconciling your work.'
      } else {
        state.error = error instanceof Error ? error.message : 'Unable to approve the document.'
      }
    } finally {
      release(actionId)
    }
  }

  function decide(findingId: string, action: DecisionAction, note?: string) {
    if (mutationsFrozen()) return
    state.decisions[findingId] = { finding_id: findingId, action, note: note || null }
  }

  function applyInnerContent(node: JSONContent, text: string) {
    const current = node.content?.[0]
    const level = current?.type === 'heading' ? headingLevelFromNode(current) : headingLevel(node.attrs?.sourceKind)
    node.content = [level ? { type: 'heading', attrs: { level }, content: textContent(text) } : { type: 'paragraph', content: textContent(text) }]
  }

  function headingLevelFromNode(node: JSONContent): 2 | 3 | null {
    return node.attrs?.level === 3 ? 3 : node.attrs?.level === 2 ? 2 : null
  }

  function applyTolerance(findingId: string, nodeId: string, replacement: string, regionHash: string) {
    if (mutationsFrozen()) return
    const finding = state.server?.findings.find((item) => item.finding_id === findingId)
    const suggestion = finding?.suggested_replacement
    const page = state.server?.catalogue.nodes.find((node) => node.node_id === nodeId)?.page_number
    if (!page || !finding || !suggestion) return
    if (
      !suggestion.eligible
      || suggestion.node_id !== nodeId
      || suggestion.text !== replacement
      || suggestion.expected_region_hash !== regionHash
      || finding.region_hash !== regionHash
    ) {
      state.contentError = 'This suggestion is no longer valid. Save and re-evaluate before applying it.'
      return
    }
    const draft = state.drafts[page]
    const current = editableTextMap(draft).get(nodeId)
    const baseline = state.baselines[page]?.get(nodeId)
    if (current === undefined) return
    if (current !== replacement && current !== baseline) {
      state.contentError = 'This suggestion no longer matches the current region. Save your edits and re-evaluate before applying it.'
      return
    }
    if (current !== replacement) {
      const next = JSON.parse(JSON.stringify(draft)) as JSONContent
      const edit = (node: JSONContent) => {
        if (node.attrs?.sourceId === nodeId) applyInnerContent(node, replacement)
        else node.content?.forEach(edit)
      }
      edit(next)
      state.drafts[page] = next
    }
    state.activePage = page
    state.contentError = null
    state.decisions[findingId] = {
      finding_id: findingId,
      action: 'RESOLVED_AFTER_EDIT',
      replacement: { node_id: nodeId, text: replacement },
      expected_region_hash: regionHash,
    }
  }

  return {
    state,
    dirty,
    changes,
    unsupported,
    blocked,
    attemptedWork,
    load,
    reloadServer: load,
    save,
    retrySameSave,
    checkSaveStatus,
    acknowledgeAttemptedSave,
    approvePage,
    approveDocument,
    decide,
    applyTolerance,
    abandonWorkspace() {
      bumpGeneration()
      actionSeq += 1
      activeAction = null
      state.pending = false
    },
    setDraft: (draft: JSONContent) => {
      if (mutationsFrozen()) return
      state.drafts[state.activePage] = draft
      invalidateDivergedReplacements()
      state.contentError = null
    },
    setContentError: (message: string) => {
      state.contentError = message
    },
  }
}

function describeAttemptedWork(record: PendingSaveRecord | null, server: ReviewStateResponse | null): AttemptedWorkView | null {
  if (!record) return null
  const parsed = parseFrozenBody(record.body)
  if (!parsed) return { changes: [], decisions: [], textItems: [], decisionItems: [] }
  const textItems = parsed.changes.map((change) => {
    const node = server?.catalogue.nodes.find((item) => item.node_id === change.node_id)
    return {
      pageLabel: node ? `Page ${node.page_number}` : 'Unknown page',
      text: change.text,
    }
  })
  const decisionItems = parsed.decisions.map((decision) => {
    const finding = server?.findings.find((item) => item.finding_id === decision.finding_id)
    const nodeId = decision.replacement?.node_id ?? finding?.node_ids[0]
    const node = nodeId ? server?.catalogue.nodes.find((item) => item.node_id === nodeId) : undefined
    const pages = finding?.pages?.length ? finding.pages : node ? [node.page_number] : []
    return {
      actionLabel: ACTION_LABELS[decision.action],
      findingLabel: finding?.code === TOLERANCE_AMBIGUITY_CODE ? 'Possible tolerance-symbol ambiguity' : 'Document finding',
      pageLabel: pages.length === 1 ? `Page ${pages[0]}` : pages.length ? `Pages ${pages.join(', ')}` : 'Unknown page',
      replacement: decision.replacement?.text ?? null,
      note: decision.note ?? null,
    }
  })
  return { changes: parsed.changes, decisions: parsed.decisions, textItems, decisionItems }
}
