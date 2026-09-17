import type { JSONContent } from '@tiptap/core'
import { computed, reactive } from 'vue'
import { ReviewApiError, type ReviewApi } from './api'
import type { DecisionAction, FindingDecisionRequest, RequestedChange, ReviewFinding, ReviewStateResponse } from './contracts'
import { editableTextMap, headingLevel, projectPage, sparseChanges, structuralSignature, textContent, validateSkeleton } from './mapping'

export const TOLERANCE_AMBIGUITY_CODE = 'POSSIBLE_TOLERANCE_SYMBOL_AMBIGUITY'

export function unresolvedToleranceNodeIds(findings: ReviewFinding[]): string[] {
  const ids: string[] = []
  for (const finding of findings) {
    if (finding.code !== TOLERANCE_AMBIGUITY_CODE) continue
    if (finding.decision?.region_hash === finding.region_hash) continue
    ids.push(...finding.node_ids)
  }
  return [...new Set(ids)]
}

export interface ReviewWorkspaceState {
  server: ReviewStateResponse | null
  drafts: Record<number, JSONContent>
  baselines: Record<number, Map<string, string>>
  skeletons: Record<number, unknown>
  unsupported: Record<number, string[]>
  decisions: Record<string, FindingDecisionRequest>
  loading: boolean
  pending: boolean
  error: string | null
  contentError: string | null
  saveStatus: 'SAVED' | 'SAVING' | 'SAVE_FAILED'
  conflict: boolean
  activePage: number
}

export function createReviewState(api: ReviewApi) {
  const state = reactive<ReviewWorkspaceState>({
    server: null,
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
  })

  const changes = computed(() =>
    Object.entries(state.drafts).flatMap(([page, draft]) =>
      sparseChanges(state.baselines[Number(page)] ?? new Map(), draft),
    ),
  )
  const dirty = computed(() => changes.value.length > 0 || Object.keys(state.decisions).length > 0)
  const unsupported = computed(() => Object.values(state.unsupported).flat())

  function acceptServer(server: ReviewStateResponse) {
    // Server revision is source of truth after a successful write; local drafts and pending decisions are discarded.
    state.server = server
    state.drafts = {}
    state.baselines = {}
    state.skeletons = {}
    state.unsupported = {}
    for (const page of server.document.pages) {
      const projection = projectPage(server, page.number)
      state.drafts[page.number] = projection.doc
      state.baselines[page.number] = projection.baselineTexts
      state.skeletons[page.number] = structuralSignature(projection.doc)
      state.unsupported[page.number] = projection.unsupported
    }
    state.decisions = {}
    state.activePage = Math.min(Math.max(state.activePage, 1), Math.max(server.document.pages.length, 1))
    state.contentError = null
    state.conflict = false
    state.saveStatus = 'SAVED'
  }

  async function load() {
    state.loading = true
    state.error = null
    try {
      acceptServer(await api.load())
    } catch (error) {
      state.error = error instanceof Error ? error.message : 'Unable to load the review.'
    } finally {
      state.loading = false
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

  function recordError(error: unknown, fallback: string) {
    if (error instanceof ReviewApiError && error.code === 'REVIEW_CONFLICT') {
      state.conflict = true
      state.error = 'The server review changed. Your draft is preserved; reload only after reconciling your work.'
    } else {
      state.error = error instanceof Error ? error.message : fallback
    }
  }

  function currentTexts(): Map<string, string> {
    const texts = new Map<string, string>()
    for (const draft of Object.values(state.drafts)) {
      for (const [nodeId, text] of editableTextMap(draft)) texts.set(nodeId, text)
    }
    return texts
  }

  function invalidateDivergedReplacements(texts = currentTexts()) {
    // Editing a suggestion preview invalidates the queued decision; the newer text is a manual change.
    for (const [findingId, decision] of Object.entries(state.decisions)) {
      const replacement = decision.replacement
      if (!replacement) continue
      if (texts.get(replacement.node_id) !== replacement.text) delete state.decisions[findingId]
    }
  }

  function saveChanges(): RequestedChange[] {
    // Suggested ± replacements are applied by the backend decision; identical preview text is omitted from sparse changes.
    const replacements = new Map(
      Object.values(state.decisions)
        .filter((decision) => decision.replacement)
        .map((decision) => [decision.replacement!.node_id, decision.replacement!.text]),
    )
    return changes.value.filter((change) => replacements.get(change.node_id) !== change.text)
  }

  async function save(force = false): Promise<boolean> {
    if (!state.server || state.pending) return false
    const invalid = validationErrors()
    if (invalid.length) {
      state.contentError = invalid[0]
      return false
    }
    invalidateDivergedReplacements()
    if (!force && !dirty.value) return true
    state.pending = true
    state.saveStatus = 'SAVING'
    state.error = null
    try {
      const updated = await api.save(state.server.revision_id, saveChanges(), Object.values(state.decisions))
      acceptServer(updated)
      return true
    } catch (error) {
      state.saveStatus = 'SAVE_FAILED'
      recordError(error, 'Unable to save the review.')
      return false
    } finally {
      state.pending = false
    }
  }

  async function approvePage(): Promise<void> {
    if (!state.server || !(await save(state.server.revision_id === null))) return
    const revision = state.server?.revision_id
    if (!revision) return
    state.pending = true
    try {
      acceptServer(await api.approvePage(state.activePage, revision))
    } catch (error) {
      recordError(error, 'Unable to approve the page.')
    } finally {
      state.pending = false
    }
  }

  async function approveDocument(): Promise<void> {
    if (!state.server || !(await save(state.server.revision_id === null))) return
    const revision = state.server?.revision_id
    if (!revision) return
    state.pending = true
    try {
      acceptServer(await api.approve(revision))
    } catch (error) {
      recordError(error, 'Unable to approve the document.')
    } finally {
      state.pending = false
    }
  }

  function decide(findingId: string, action: DecisionAction, note?: string) {
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
    load,
    reloadServer: load,
    save,
    approvePage,
    approveDocument,
    decide,
    applyTolerance,
    setDraft: (draft: JSONContent) => {
      state.drafts[state.activePage] = draft
      invalidateDivergedReplacements()
      state.contentError = null
    },
    setContentError: (message: string) => {
      state.contentError = message
    },
  }
}
